from square.core.api_error import ApiError

from app.client import create_square_client
from app.order_processing_store import (
    PROCESSING_STATE_APPLIED,
    get_order_processing_state,
)


def normalize_square_order_for_inventory_plan(order):
    return {
        "id": order.id,
        "location_id": order.location_id,
        "state": order.state,
        "line_items": [
            {
                "uid": line_item.uid,
                "name": line_item.name,
                "quantity": line_item.quantity,
                "catalog_object_id": line_item.catalog_object_id,
                "modifiers": [
                    {
                        "uid": modifier.uid,
                        "name": modifier.name,
                        "quantity": modifier.quantity,
                        "catalog_object_id": modifier.catalog_object_id,
                    }
                    for modifier in (line_item.modifiers or [])
                ],
            }
            for line_item in (order.line_items or [])
        ],
    }


def load_order_summaries_for_processing(order_ids, client=None):
    client = client or create_square_client()
    order_summaries = []
    skipped_orders = []

    for order_id in order_ids:
        try:
            response = client.orders.get(order_id=order_id)
        except ApiError as error:
            skipped_orders.append(
                {
                    "order_id": order_id,
                    "reason": f"Square API error: {error}",
                }
            )
            continue

        order = response.order
        if not order:
            skipped_orders.append(
                {
                    "order_id": order_id,
                    "reason": "Order not found",
                }
            )
            continue

        if order.state != "COMPLETED":
            skipped_orders.append(
                {
                    "order_id": order.id,
                    "state": order.state,
                    "reason": "Order is not COMPLETED",
                }
            )
            continue

        if get_order_processing_state(order.id) == PROCESSING_STATE_APPLIED:
            skipped_orders.append(
                {
                    "order_id": order.id,
                    "state": order.state,
                    "reason": "Order already processed",
                }
            )
            continue

        order_summaries.append(normalize_square_order_for_inventory_plan(order))

    return order_summaries, skipped_orders
