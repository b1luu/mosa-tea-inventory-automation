from app.client import create_square_client_for_merchant
from app.config import get_square_environment_name
from app.merchant_store import (
    get_active_catalog_binding,
    get_merchant_context,
    get_merchant_write_readiness,
    get_write_blocker_message,
)
from app.order_processing_db import CLAIM_LEASE_SECONDS
from app.order_processing_store import (
    PROCESSING_STATE_APPLIED,
    PROCESSING_STATE_BLOCKED,
    PROCESSING_STATE_CANCELLED_BEFORE_APPLY,
    PROCESSING_STATE_FAILED,
    PROCESSING_STATE_PENDING,
    PROCESSING_STATE_PROCESSING,
    claim_order_processing,
    get_order_processing_record,
    get_order_processing_state,
    mark_order_applied,
    mark_order_blocked,
    mark_order_cancelled_before_apply,
    mark_order_failed,
    release_order_processing_claim,
    requeue_order_processing,
)
from app.order_processor import process_orders
from app.usage_log_store import record_order_usage
from app.webhook_event_store import (
    EVENT_STATUS_FAILED,
    EVENT_STATUS_PROCESSED,
    set_webhook_event_status,
)


class RetryableWebhookJobError(RuntimeError):
    pass


# A duplicate delivery for an order in one of these states is a no-op.
TERMINAL_PROCESSING_STATES = frozenset(
    {
        PROCESSING_STATE_APPLIED,
        PROCESSING_STATE_BLOCKED,
        PROCESSING_STATE_CANCELLED_BEFORE_APPLY,
        PROCESSING_STATE_FAILED,
    }
)


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


def _build_blocked_result(reason, *, blockers=None, base_result=None):
    result = dict(base_result or _build_empty_result())
    result["processing_outcome"] = PROCESSING_STATE_BLOCKED
    result["blocking_reason"] = reason
    if blockers is not None:
        result["blocking_reasons"] = list(blockers)
    inventory_response = result.get("inventory_response") or {}
    result["inventory_response"] = {
        **inventory_response,
        "blocked_reason": reason,
    }
    if blockers is not None:
        result["inventory_response"]["blocked_reasons"] = list(blockers)
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

    # Paid orders are held before apply; one cancelled during the hold is a
    # normal outcome, not a failure.
    skipped_orders = result.get("skipped_orders") or []
    if skipped_orders and all(skipped.get("state") == "CANCELED" for skipped in skipped_orders):
        return PROCESSING_STATE_CANCELLED_BEFORE_APPLY

    return PROCESSING_STATE_FAILED


def _record_applied_usage(merchant_processing_context, result):
    """Log each applied order's ingredient usage, including log-only ingredients.

    Runs before the order is marked applied: if this raises, the job is retried.
    The retry sends Square an identical request (same idempotency key, and
    occurred_at from the order's created_at; see
    order_processor.deterministic_occurred_at), so Square returns the original
    result instead of deducting again, and these rows are rewritten under the
    same keys. Orders older than 23 hours use the current time instead, so for
    them a retry after a successful write is refused and ends failed.
    """
    for projected_order in result["projected_orders"]:
        order_id = projected_order["order_id"]
        record_order_usage(
            merchant_processing_context["environment"],
            merchant_processing_context["merchant_id"],
            projected_order.get("location_id") or merchant_processing_context["location_id"],
            order_id,
            projected_order.get("created_at"),
            [
                usage
                for line_item in result.get("projected_line_items", [])
                if line_item["order_id"] == order_id
                for usage in line_item["usage"]
            ],
        )


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
    elif processing_outcome == PROCESSING_STATE_CANCELLED_BEFORE_APPLY:
        transitioned = mark_order_cancelled_before_apply(order_id)
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
            _resolve_merchant_processing_context(job) if job else None
        )

        # No env-token fallback: every write must run against an explicit,
        # merchant-scoped client. If the merchant context can't be resolved,
        # fail loud rather than write to whatever account the env token holds.
        if merchant_processing_context is None:
            raise RuntimeError(
                f"Cannot process order '{order_id}' without a resolved merchant "
                f"context; refusing to fall back to the environment token for a "
                f"write."
            )

        merchant_context = merchant_processing_context["merchant_context"]
        readiness = get_merchant_write_readiness(
            merchant_processing_context["environment"],
            merchant_processing_context["merchant_id"],
            location_id=merchant_processing_context["location_id"],
            active_binding=merchant_processing_context["binding"],
            include_operator_intent=False,
        )
        if not readiness["write_ready"]:
            result = _build_blocked_result(
                get_write_blocker_message(readiness["write_blockers"][0]),
                blockers=readiness["write_blockers"],
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
                    blockers=["writes_disabled_by_operator"],
                    base_result=result,
                )
            elif _resolve_processing_outcome(result) == PROCESSING_STATE_APPLIED:
                _record_applied_usage(merchant_processing_context, result)

        processing_state = _transition_claimed_order_to_terminal_state(order_id, result)
    except Exception:
        release_order_processing_claim(order_id)
        raise

    return processing_state, result


def _build_replay_job(order_id):
    # Replay must run through the same merchant-scoped path as a live webhook:
    # the merchant's OAuth client, their binding, and the write-readiness gates.
    # The merchant context lives on the order_processing row (persisted at
    # ingest). Orders reserved before that persistence carry no merchant_id and
    # are intentionally not safe to replay — refuse rather than fall back to the
    # environment token.
    record = get_order_processing_record(order_id)
    merchant_id = (record or {}).get("merchant_id")
    if not merchant_id:
        raise RuntimeError(
            f"Cannot replay order '{order_id}' safely: no merchant context is "
            f"recorded for it. Orders that were never ingested, or were reserved "
            f"before merchant-context persistence, cannot be replayed through the "
            f"merchant-scoped path."
        )
    return {
        "order_id": order_id,
        "merchant_id": merchant_id,
        "environment": record.get("environment"),
        "location_id": record.get("location_id"),
    }


def _process_order_job(order_id, *, job=None):
    claimed = claim_order_processing(order_id)
    if claimed:
        return _process_claimed_order(order_id, job=job)

    current_state = get_order_processing_state(order_id)
    if current_state in TERMINAL_PROCESSING_STATES:
        return current_state, None

    raise RetryableWebhookJobError(
        f"Order '{order_id}' is not ready for worker processing. "
        f"Current state: {current_state!r}."
    )


def replay_order_job(order_id):
    current_processing_state = get_order_processing_state(order_id)

    if current_processing_state == PROCESSING_STATE_APPLIED:
        raise RuntimeError(f"Order '{order_id}' is already applied.")

    # Validate replayability BEFORE mutating state. If the order has no recorded
    # merchant context it cannot be routed through the merchant-scoped path, so
    # refuse here and leave it in its current (FAILED/BLOCKED) state rather than
    # degrading it to a PENDING limbo or reserving a phantom row.
    job = _build_replay_job(order_id)

    if current_processing_state in {
        PROCESSING_STATE_FAILED,
        PROCESSING_STATE_BLOCKED,
    }:
        prepared = requeue_order_processing(order_id)
    elif current_processing_state in {
        PROCESSING_STATE_PENDING,
        # Left by a run that was killed (Lambda timeout) before it could release
        # its claim. The claim below takes it over only once the lease has passed,
        # the same check a live SQS retry uses, so a live run is never taken over.
        PROCESSING_STATE_PROCESSING,
    }:
        prepared = True
    else:
        raise RuntimeError(
            f"Order '{order_id}' cannot be replayed from state "
            f"{current_processing_state!r}."
        )

    if not prepared:
        raise RuntimeError(
            f"Order '{order_id}' could not be prepared for replay from state "
            f"{current_processing_state!r}."
        )

    try:
        processing_state_after, result = _process_order_job(order_id, job=job)
    except RetryableWebhookJobError:
        if current_processing_state != PROCESSING_STATE_PROCESSING:
            raise
        raise RuntimeError(
            f"Order '{order_id}' is claimed by a run less than "
            f"{CLAIM_LEASE_SECONDS} s old, which may still be alive. If it was "
            f"killed, replay again once the claim is {CLAIM_LEASE_SECONDS} s old."
        ) from None
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
            if current_state in TERMINAL_PROCESSING_STATES:
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
