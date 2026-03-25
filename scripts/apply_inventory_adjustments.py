import json
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from square.core.api_error import ApiError

from app.client import create_square_client
from app.order_inventory_projection import project_line_item_usage
from app.processed_orders_state import (
    load_processed_order_ids,
    mark_orders_processed,
)


def _serialize_response_model(response):
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    return str(response)


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.apply_inventory_adjustments "
        "[--apply] <order_id> [<order_id> ...]"
    )


def _parse_args(argv):
    apply_changes = False
    order_ids = []

    for arg in argv:
        if arg == "--apply":
            apply_changes = True
            continue
        order_ids.append(arg)

    if not order_ids:
        raise ValueError(_usage())

    return apply_changes, order_ids


def _extract_line_items(order):
    extracted = []

    for line_item in order.line_items or []:
        if not line_item.catalog_object_id:
            continue

        extracted.append(
            {
                "order_id": order.id,
                "location_id": order.location_id,
                "sold_variation_id": line_item.catalog_object_id,
                "quantity": line_item.quantity,
                "name": line_item.name,
                "modifier_ids": [
                    modifier.catalog_object_id
                    for modifier in (line_item.modifiers or [])
                    if modifier.catalog_object_id
                ],
            }
        )

    return extracted


def _combine_usage_by_location(projected_line_items):
    combined = {}

    for projected_line_item in projected_line_items:
        location_id = projected_line_item["location_id"]
        for usage in projected_line_item.get("usage", []):
            key = (location_id, usage["inventory_key"])

            if key not in combined:
                combined[key] = {
                    "location_id": location_id,
                    "inventory_key": usage["inventory_key"],
                    "square_variation_id": usage["square_variation_id"],
                    "inventory_unit": usage["inventory_unit"],
                    "total_amount": Decimal("0"),
                }

            combined[key]["total_amount"] += Decimal(str(usage["total_amount"]))

    return [
        {
            **value,
            "total_amount": float(value["total_amount"]),
        }
        for value in combined.values()
    ]


def _build_adjustment_changes(combined_usage, occurred_at):
    changes = []

    for usage in combined_usage:
        quantity = Decimal(str(usage["total_amount"]))
        if quantity <= 0:
            continue

        changes.append(
            {
                "type": "ADJUSTMENT",
                "adjustment": {
                    "reference_id": str(uuid.uuid4()),
                    "catalog_object_id": usage["square_variation_id"],
                    "from_state": "IN_STOCK",
                    "to_state": "WASTE",
                    "location_id": usage["location_id"],
                    "quantity": str(quantity),
                    "occurred_at": occurred_at,
                },
            }
        )

    return changes


def main():
    try:
        apply_changes, order_ids = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    client = create_square_client()
    already_processed_order_ids = load_processed_order_ids()
    projected_orders = []
    skipped_orders = []
    skipped_line_items = []
    projected_line_items = []

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

        if order.id in already_processed_order_ids:
            skipped_orders.append(
                {
                    "order_id": order.id,
                    "state": order.state,
                    "reason": "Order already processed",
                }
            )
            continue

        extracted_line_items = _extract_line_items(order)
        projected_orders.append(
            {
                "order_id": order.id,
                "location_id": order.location_id,
                "state": order.state,
                "line_item_count": len(extracted_line_items),
            }
        )

        for line_item in extracted_line_items:
            try:
                projected_line_item = project_line_item_usage(
                    line_item["sold_variation_id"],
                    line_item["quantity"],
                    line_item["modifier_ids"],
                )
                projected_line_items.append(
                    {
                        **projected_line_item,
                        "order_id": line_item["order_id"],
                        "location_id": line_item["location_id"],
                    }
                )
            except Exception as error:
                skipped_line_items.append(
                    {
                        **line_item,
                        "reason": str(error),
                    }
                )

    combined_usage = _combine_usage_by_location(projected_line_items)
    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    changes = _build_adjustment_changes(combined_usage, occurred_at)
    request_body = {
        "idempotency_key": str(uuid.uuid4()),
        "changes": changes,
        "ignore_unchanged_counts": True,
    }

    api_result = None
    if apply_changes and changes:
        try:
            response = client.inventory.batch_create_changes(**request_body)
            api_result = _serialize_response_model(response)
            mark_orders_processed([order["order_id"] for order in projected_orders])
        except ApiError as error:
            api_result = {"error": f"Square API error: {error}"}
    elif apply_changes:
        api_result = {"message": "No inventory changes to apply."}

    print("mode:")
    print(json.dumps({"apply": apply_changes}, indent=2))
    print("projected_orders:")
    print(json.dumps(projected_orders, indent=2))
    print("skipped_orders:")
    print(json.dumps(skipped_orders, indent=2))
    print("skipped_line_items:")
    print(json.dumps(skipped_line_items, indent=2))
    print("projected_line_items:")
    print(json.dumps(projected_line_items, indent=2))
    print("combined_usage:")
    print(json.dumps(combined_usage, indent=2))
    print("inventory_request:")
    print(json.dumps(request_body, indent=2))

    if api_result is not None:
        print("inventory_response:")
        print(json.dumps(api_result, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
