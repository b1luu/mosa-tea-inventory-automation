import uuid
from datetime import datetime, timezone
from decimal import Decimal

from square.core.api_error import ApiError

from app.client import create_square_client
from app.inventory_stock_units import (
    convert_inventory_amount_to_stock_unit,
    has_stock_unit_mapping,
    summarize_combined_usage_in_display_units,
)
from app.order_inventory_projection import project_line_item_usage
from app.order_processing_store import (
    PROCESSING_STATE_BLOCKED,
    mark_order_blocked,
    mark_order_failed,
    mark_order_pending,
    set_order_processing_state,
)
from app.processed_orders_state import load_processed_order_ids, mark_orders_processed


def _quantized_decimal_string(value):
    return str(Decimal(str(value)).quantize(Decimal("0.00001")))


def _serialize_response_model(response):
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    return str(response)


def _build_request_idempotency_key(order_ids, combined_usage):
    joined_order_ids = "|".join(sorted(order_ids))
    usage_signature = "|".join(
        sorted(
            (
                f"{usage['location_id']}:"
                f"{usage['square_variation_id']}:"
                f"{_quantized_decimal_string(usage['total_amount'])}"
            )
            for usage in combined_usage
        )
    )
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"inventory-adjustments:{joined_order_ids}:{usage_signature}",
        )
    )


def _build_adjustment_reference_id(order_ids, usage):
    joined_order_ids = "|".join(sorted(order_ids))
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            (
                "inventory-adjustment:"
                f"{joined_order_ids}:"
                f"{usage['location_id']}:"
                f"{usage['square_variation_id']}:"
                f"{_quantized_decimal_string(usage['total_amount'])}"
            ),
        )
    )


def _extract_line_items(order):
    extracted = []
    skipped = []

    for line_item in order.line_items or []:
        if not line_item.catalog_object_id:
            skipped.append(
                {
                    "order_id": order.id,
                    "location_id": order.location_id,
                    "sold_variation_id": None,
                    "quantity": line_item.quantity,
                    "name": line_item.name,
                    "modifier_ids": [
                        modifier.catalog_object_id
                        for modifier in (line_item.modifiers or [])
                        if modifier.catalog_object_id
                    ],
                    "reason": "Line item has no catalog_object_id and cannot be projected.",
                }
            )
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

    return extracted, skipped


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
        value
        for value in combined.values()
    ]


def _build_adjustment_changes(order_ids, combined_usage, occurred_at):
    changes = []

    for usage in combined_usage:
        quantity = Decimal(str(usage["total_amount"]))
        if has_stock_unit_mapping(usage["inventory_key"]):
            converted = convert_inventory_amount_to_stock_unit(
                usage["inventory_key"],
                usage["total_amount"],
            )
            quantity = Decimal(str(converted["stock_unit_amount"]))
        if quantity <= 0:
            continue
        quantity = quantity.quantize(Decimal("0.00001"))

        changes.append(
            {
                "type": "ADJUSTMENT",
                "adjustment": {
                    "reference_id": _build_adjustment_reference_id(order_ids, usage),
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


def process_orders(order_ids, apply_changes=False):
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

        extracted_line_items, skipped_extracted_line_items = _extract_line_items(order)
        skipped_line_items.extend(skipped_extracted_line_items)
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
    display_usage = summarize_combined_usage_in_display_units(combined_usage)
    occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    projected_order_ids = [order["order_id"] for order in projected_orders]
    changes = _build_adjustment_changes(projected_order_ids, combined_usage, occurred_at)
    request_body = {
        "idempotency_key": _build_request_idempotency_key(
            projected_order_ids,
            combined_usage,
        ),
        "changes": changes,
        "ignore_unchanged_counts": True,
    }

    api_result = None
    if apply_changes and skipped_line_items:
        for order in projected_orders:
            mark_order_pending(order["order_id"])
            mark_order_blocked(order["order_id"])
        api_result = {
            "error": (
                "Refusing to apply inventory changes because one or more line items "
                "were skipped during projection."
            )
        }
    elif apply_changes and changes:
        for order in projected_orders:
            mark_order_pending(order["order_id"])
        try:
            response = client.inventory.batch_create_changes(**request_body)
            api_result = _serialize_response_model(response)
            mark_orders_processed([order["order_id"] for order in projected_orders])
        except ApiError as error:
            for order in projected_orders:
                mark_order_failed(order["order_id"])
            api_result = {"error": f"Square API error: {error}"}
    elif apply_changes:
        api_result = {"message": "No inventory changes to apply."}

    return {
        "mode": {"apply": apply_changes},
        "projected_orders": projected_orders,
        "skipped_orders": skipped_orders,
        "skipped_line_items": skipped_line_items,
        "projected_line_items": projected_line_items,
        "combined_usage": combined_usage,
        "display_usage": display_usage,
        "inventory_request": request_body,
        "inventory_response": api_result,
    }
