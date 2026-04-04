from app.client import create_square_client_for_merchant
from app.config import get_square_environment_name
from app.merchant_store import get_active_catalog_binding, get_merchant_context
from app.order_processing_store import (
    PROCESSING_STATE_APPLIED,
    PROCESSING_STATE_BLOCKED,
    PROCESSING_STATE_FAILED,
    PROCESSING_STATE_PENDING,
    PROCESSING_STATE_PROCESSING,
    claim_order_processing,
    get_order_processing_state,
    mark_order_applied,
    mark_order_blocked,
    mark_order_failed,
    release_order_processing_claim,
    reserve_order_processing,
    requeue_order_processing,
)
from app.order_processor import process_orders
from app.webhook_event_store import (
    EVENT_STATUS_FAILED,
    EVENT_STATUS_PROCESSED,
    set_webhook_event_status,
)


class RetryableWebhookJobError(RuntimeError):
    pass


def _build_empty_result():
    return {
        "mode": {"apply": False},
        "projected_orders": [],
        "skipped_orders": [],
        "skipped_line_items": [],
        "projected_line_items": [],
        "combined_usage": [],
        "display_usage": [],
        "inventory_request": {},
        "inventory_response": None,
    }


def _build_blocked_result(reason, *, base_result=None):
    result = dict(base_result or _build_empty_result())
    result["processing_outcome"] = PROCESSING_STATE_BLOCKED
    result["blocking_reason"] = reason
    inventory_response = result.get("inventory_response") or {}
    result["inventory_response"] = {
        **inventory_response,
        "blocked_reason": reason,
    }
    return result


def _resolve_processing_outcome(result):
    explicit_outcome = result.get("processing_outcome")
    if explicit_outcome in {
        PROCESSING_STATE_APPLIED,
        PROCESSING_STATE_BLOCKED,
        PROCESSING_STATE_FAILED,
    }:
        return explicit_outcome

    if result["skipped_line_items"]:
        return PROCESSING_STATE_BLOCKED

    inventory_response = result["inventory_response"] or {}
    if "error" in inventory_response:
        return PROCESSING_STATE_FAILED

    if result["projected_orders"]:
        return PROCESSING_STATE_APPLIED

    return PROCESSING_STATE_FAILED


def _resolve_merchant_processing_context(job):
    merchant_id = job.get("merchant_id")
    environment = job.get("environment")
    location_id = job.get("location_id")

    # Older jobs only carried order/event identifiers. Keep that path working.
    if not merchant_id or (environment is None and location_id is None):
        return None

    resolved_environment = environment or get_square_environment_name()
    merchant_context = get_merchant_context(resolved_environment, merchant_id)
    resolved_location_id = (
        location_id
        or (merchant_context.location_id if merchant_context else None)
    )
    binding = (
        get_active_catalog_binding(
            resolved_environment,
            merchant_id,
            resolved_location_id,
        )
        if merchant_context and resolved_location_id
        else None
    )
    return {
        "environment": resolved_environment,
        "merchant_id": merchant_id,
        "merchant_context": merchant_context,
        "location_id": resolved_location_id,
        "binding": binding,
    }


def _transition_claimed_order_to_terminal_state(order_id, result):
    processing_outcome = _resolve_processing_outcome(result)

    if processing_outcome == PROCESSING_STATE_APPLIED:
        transitioned = mark_order_applied(order_id)
    elif processing_outcome == PROCESSING_STATE_BLOCKED:
        transitioned = mark_order_blocked(order_id)
    else:
        transitioned = mark_order_failed(order_id)

    if not transitioned:
        current_state = get_order_processing_state(order_id)
        raise RuntimeError(
            f"Order '{order_id}' could not transition from "
            f"{PROCESSING_STATE_PROCESSING!r} to {processing_outcome!r}. "
            f"Current state: {current_state!r}."
        )

    return processing_outcome


def _process_claimed_order(order_id, *, job=None):
    try:
        merchant_processing_context = (
            _resolve_merchant_processing_context(job or {})
            if job is not None
            else None
        )

        if merchant_processing_context is None:
            result = process_orders([order_id], apply_changes=True)
        else:
            merchant_context = merchant_processing_context["merchant_context"]
            if not merchant_context or merchant_context.status != "active":
                result = _build_blocked_result(
                    "No active merchant context is available for this webhook job."
                )
            elif merchant_processing_context["binding"] is None:
                result = _build_blocked_result(
                    "No approved catalog binding is available for this merchant/location."
                )
            else:
                merchant_client = create_square_client_for_merchant(
                    merchant_processing_context["environment"],
                    merchant_processing_context["merchant_id"],
                )
                apply_changes = merchant_context.writes_enabled
                result = process_orders(
                    [order_id],
                    apply_changes=apply_changes,
                    client=merchant_client,
                    binding=merchant_processing_context["binding"],
                )
                if not apply_changes:
                    result = _build_blocked_result(
                        "Inventory writes are disabled pending owner approval.",
                        base_result=result,
                    )

        processing_state = _transition_claimed_order_to_terminal_state(order_id, result)
    except Exception:
        release_order_processing_claim(order_id)
        raise

    return processing_state, result


def _process_order_job(order_id):
    claimed = claim_order_processing(order_id)
    if claimed:
        return _process_claimed_order(order_id, job=None)

    current_state = get_order_processing_state(order_id)
    if current_state in {
        PROCESSING_STATE_APPLIED,
        PROCESSING_STATE_BLOCKED,
        PROCESSING_STATE_FAILED,
    }:
        return current_state, None

    raise RetryableWebhookJobError(
        f"Order '{order_id}' is not ready for worker processing. "
        f"Current state: {current_state!r}."
    )


def replay_order_job(order_id):
    current_processing_state = get_order_processing_state(order_id)

    if current_processing_state == PROCESSING_STATE_APPLIED:
        raise RuntimeError(f"Order '{order_id}' is already applied.")

    if current_processing_state == PROCESSING_STATE_PROCESSING:
        raise RuntimeError(f"Order '{order_id}' is already being processed.")

    if current_processing_state is None:
        prepared = reserve_order_processing(order_id)
    elif current_processing_state in {
        PROCESSING_STATE_FAILED,
        PROCESSING_STATE_BLOCKED,
    }:
        prepared = requeue_order_processing(order_id)
    elif current_processing_state == PROCESSING_STATE_PENDING:
        prepared = True
    else:
        prepared = False

    if not prepared:
        raise RuntimeError(
            f"Order '{order_id}' could not be prepared for replay from state "
            f"{current_processing_state!r}."
        )

    processing_state_after, result = _process_order_job(order_id)
    return {
        "order_id": order_id,
        "current_processing_state": current_processing_state,
        "processing_state_after": processing_state_after,
        "mode": result["mode"] if result else {"apply": True},
        "projected_orders": result["projected_orders"] if result else [],
        "inventory_response": result["inventory_response"] if result else None,
        "skipped_orders": result["skipped_orders"] if result else [],
        "skipped_line_items": result["skipped_line_items"] if result else [],
        "projected_line_items": result["projected_line_items"] if result else [],
        "combined_usage": result["combined_usage"] if result else [],
        "display_usage": result["display_usage"] if result else [],
        "inventory_request": result["inventory_request"] if result else {},
    }


def process_webhook_job(job):
    event_id = job.get("event_id")

    try:
        order_id = job["order_id"]
        claimed = claim_order_processing(order_id)
        if claimed:
            processing_state, _ = _process_claimed_order(order_id, job=job)
        else:
            current_state = get_order_processing_state(order_id)
            if current_state in {
                PROCESSING_STATE_APPLIED,
                PROCESSING_STATE_BLOCKED,
                PROCESSING_STATE_FAILED,
            }:
                processing_state = current_state
            else:
                raise RetryableWebhookJobError(
                    f"Order '{order_id}' is not ready for worker processing. "
                    f"Current state: {current_state!r}."
                )
        if event_id:
            event_status = (
                EVENT_STATUS_FAILED
                if processing_state == PROCESSING_STATE_FAILED
                else EVENT_STATUS_PROCESSED
            )
            set_webhook_event_status(event_id, event_status)
        return processing_state
    except RetryableWebhookJobError:
        raise
    except Exception:
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_FAILED)
        raise
