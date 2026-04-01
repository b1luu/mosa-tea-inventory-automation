from app.order_processing_store import (
    PROCESSING_STATE_APPLIED,
    PROCESSING_STATE_BLOCKED,
    get_order_processing_state,
)
from app.order_processor import process_orders
from app.webhook_event_store import (
    EVENT_STATUS_FAILED,
    EVENT_STATUS_PROCESSED,
    set_webhook_event_status,
)


def process_webhook_job(job):
    event_id = job.get("event_id")

    try:
        order_id = job["order_id"]
        process_orders([order_id], apply_changes=True)
        processing_state = get_order_processing_state(order_id)
        if processing_state not in {
            PROCESSING_STATE_APPLIED,
            PROCESSING_STATE_BLOCKED,
        }:
            raise RuntimeError(
                f"Webhook job for order '{order_id}' did not reach a terminal successful state. "
                f"Current processing state: {processing_state!r}."
            )
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_PROCESSED)
        return processing_state
    except Exception:
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_FAILED)
        raise
