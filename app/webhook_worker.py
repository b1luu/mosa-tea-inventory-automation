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


def _resolve_processing_outcome(result):
    if result["skipped_line_items"]:
        return PROCESSING_STATE_BLOCKED

    inventory_response = result["inventory_response"] or {}
    if "error" in inventory_response:
        return PROCESSING_STATE_FAILED

    if result["projected_orders"]:
        return PROCESSING_STATE_APPLIED

    return PROCESSING_STATE_FAILED


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


def _process_claimed_order(order_id):
    try:
        result = process_orders([order_id], apply_changes=True)
        processing_state = _transition_claimed_order_to_terminal_state(order_id, result)
    except Exception:
        release_order_processing_claim(order_id)
        raise

    return processing_state, result


def _process_order_job(order_id):
    claimed = claim_order_processing(order_id)
    if claimed:
        return _process_claimed_order(order_id)

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
        processing_state, _ = _process_order_job(order_id)
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
