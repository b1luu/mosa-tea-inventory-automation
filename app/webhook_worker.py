from app.order_processor import process_orders
from app.webhook_event_store import (
    EVENT_STATUS_FAILED,
    EVENT_STATUS_PROCESSED,
    set_webhook_event_status,
)


def process_webhook_job(job):
    order_id = job["order_id"]
    event_id = job.get("event_id")

    try:
        process_orders([order_id], apply_changes=True)
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_PROCESSED)
    except Exception:
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_FAILED)
        raise
