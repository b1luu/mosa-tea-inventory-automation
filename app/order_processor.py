from square.core.api_error import ApiError

from app.client import create_square_client
from app.inventory_plan import (
    _build_adjustment_changes,
    build_inventory_plan_from_order_summaries,
)
from app.order_processing_store import (
    PROCESSING_STATE_APPLIED,
    get_order_processing_state,
)

def _serialize_response_model(response):
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    return str(response)


def _summarize_order_for_planning(order):
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

        order_summaries.append(_summarize_order_for_planning(order))

    return order_summaries, skipped_orders


def build_inventory_plan(order_summaries, *, skipped_orders=None):
    return build_inventory_plan_from_order_summaries(
        order_summaries,
        skipped_orders=skipped_orders,
    )


def apply_inventory_plan(plan, *, apply_changes=False, client=None):
    if not apply_changes:
        return None

    if not plan.can_apply:
        return {"error": plan.blocking_reason}

    if not plan.inventory_request["changes"]:
        return {"message": "No inventory changes to apply."}

    client = client or create_square_client()
    try:
        response = client.inventory.batch_create_changes(**plan.inventory_request)
        return _serialize_response_model(response)
    except ApiError as error:
        return {"error": f"Square API error: {error}"}


def process_orders(order_ids, apply_changes=False):
    client = create_square_client()
    order_summaries, skipped_orders = load_order_summaries_for_processing(
        order_ids,
        client=client,
    )
    plan = build_inventory_plan(order_summaries, skipped_orders=skipped_orders)
    api_result = apply_inventory_plan(plan, apply_changes=apply_changes, client=client)

    return {
        "mode": {"apply": apply_changes},
        **plan.to_dict(),
        "inventory_response": api_result,
    }
