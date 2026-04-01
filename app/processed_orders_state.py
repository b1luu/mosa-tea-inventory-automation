from app.order_processing_store import (
    PROCESSING_STATE_APPLIED,
    list_order_processing_rows,
    mark_order_applied,
)


def load_processed_order_ids():
    rows = list_order_processing_rows(processing_state=PROCESSING_STATE_APPLIED)
    return {row["square_order_id"] for row in rows}


def mark_orders_processed(order_ids):
    for order_id in order_ids:
        mark_order_applied(order_id)
