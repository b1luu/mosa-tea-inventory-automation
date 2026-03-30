from app.order_processor import process_orders
from app.webhook_event_db import (
    EVENT_STATUS_FAILED,
    EVENT_STATUS_PROCESSED,
    set_webhook_event_status,
)


def process_order_webhook_event(order_id, event_id=None):
    try:
        process_orders([order_id], apply_changes=True)
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_PROCESSED)
    except Exception:
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_FAILED)
        raise
