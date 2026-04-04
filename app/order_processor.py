from square.core.api_error import ApiError

from app.client import create_square_client
from app.inventory_plan import (
    _build_adjustment_changes,
    build_inventory_plan_from_order_summaries,
)
from app.order_loader import load_order_summaries_for_processing

def _serialize_response_model(response):
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    return str(response)


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


def process_order_summaries(
    order_summaries,
    *,
    skipped_orders=None,
    apply_changes=False,
    client=None,
):
    plan = build_inventory_plan(order_summaries, skipped_orders=skipped_orders)
    api_result = apply_inventory_plan(plan, apply_changes=apply_changes, client=client)

    return {
        "mode": {"apply": apply_changes},
        **plan.to_dict(),
        "inventory_response": api_result,
    }


def process_orders(order_ids, apply_changes=False):
    client = create_square_client()
    order_summaries, skipped_orders = load_order_summaries_for_processing(
        order_ids,
        client=client,
    )
    return process_order_summaries(
        order_summaries,
        skipped_orders=skipped_orders,
        apply_changes=apply_changes,
        client=client,
    )
