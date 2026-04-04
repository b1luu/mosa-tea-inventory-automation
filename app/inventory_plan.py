import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.inventory_stock_units import (
    convert_inventory_amount_to_stock_unit,
    has_stock_unit_mapping,
    summarize_combined_usage_in_display_units,
)
from app.order_inventory_projection import project_line_item_usage


@dataclass(frozen=True)
class InventoryPlan:
    projected_orders: list
    skipped_orders: list
    skipped_line_items: list
    projected_line_items: list
    combined_usage: list
    display_usage: list
    inventory_request: dict
    can_apply: bool
    blocking_reason: str | None

    def to_dict(self):
        return {
            "projected_orders": self.projected_orders,
            "skipped_orders": self.skipped_orders,
            "skipped_line_items": self.skipped_line_items,
            "projected_line_items": self.projected_line_items,
            "combined_usage": self.combined_usage,
            "display_usage": self.display_usage,
            "inventory_request": self.inventory_request,
            "can_apply": self.can_apply,
            "blocking_reason": self.blocking_reason,
        }


def _quantized_decimal_string(value):
    return str(Decimal(str(value)).quantize(Decimal("0.00001")))


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


def _resolve_order_identifier(order_summary, index):
    return (
        order_summary.get("id")
        or order_summary.get("reference_id")
        or f"synthetic-order-{index + 1}"
    )


def _extract_line_items(order_summary, order_identifier):
    extracted = []
    skipped = []

    for line_item in order_summary.get("line_items") or []:
        sold_variation_id = line_item.get("catalog_object_id")
        modifier_ids = [
            modifier.get("catalog_object_id")
            for modifier in (line_item.get("modifiers") or [])
            if modifier.get("catalog_object_id")
        ]
        if not sold_variation_id:
            skipped.append(
                {
                    "order_id": order_identifier,
                    "location_id": order_summary.get("location_id"),
                    "sold_variation_id": None,
                    "quantity": line_item.get("quantity"),
                    "name": line_item.get("name"),
                    "modifier_ids": modifier_ids,
                    "reason": "Line item has no catalog_object_id and cannot be projected.",
                }
            )
            continue

        extracted.append(
            {
                "order_id": order_identifier,
                "location_id": order_summary.get("location_id"),
                "sold_variation_id": sold_variation_id,
                "quantity": line_item.get("quantity"),
                "name": line_item.get("name"),
                "modifier_ids": modifier_ids,
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

    return [value for value in combined.values()]


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


def build_inventory_plan_from_order_summaries(
    order_summaries,
    *,
    skipped_orders=None,
    occurred_at=None,
):
    projected_orders = []
    skipped_orders = list(skipped_orders or [])
    skipped_line_items = []
    projected_line_items = []

    occurred_at = (
        occurred_at
        if occurred_at is not None
        else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    projected_order_ids = []
    for index, order_summary in enumerate(order_summaries):
        order_identifier = _resolve_order_identifier(order_summary, index)
        projected_order_ids.append(order_identifier)
        extracted_line_items, skipped_extracted_line_items = _extract_line_items(
            order_summary,
            order_identifier,
        )
        skipped_line_items.extend(skipped_extracted_line_items)
        projected_orders.append(
            {
                "order_id": order_identifier,
                "location_id": order_summary.get("location_id"),
                "state": order_summary.get("state"),
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
    inventory_request = {
        "idempotency_key": _build_request_idempotency_key(
            projected_order_ids,
            combined_usage,
        ),
        "changes": _build_adjustment_changes(
            projected_order_ids,
            combined_usage,
            occurred_at,
        ),
        "ignore_unchanged_counts": True,
    }

    blocking_reason = None
    if skipped_line_items:
        blocking_reason = (
            "Refusing to apply inventory changes because one or more line items "
            "were skipped during projection."
        )

    return InventoryPlan(
        projected_orders=projected_orders,
        skipped_orders=skipped_orders,
        skipped_line_items=skipped_line_items,
        projected_line_items=projected_line_items,
        combined_usage=combined_usage,
        display_usage=display_usage,
        inventory_request=inventory_request,
        can_apply=not skipped_line_items,
        blocking_reason=blocking_reason,
    )


def build_inventory_plan_from_order_summary(order_summary, *, occurred_at=None):
    return build_inventory_plan_from_order_summaries(
        [order_summary],
        occurred_at=occurred_at,
    )
