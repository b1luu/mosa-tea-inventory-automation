import json
import sys

from square.core.api_error import ApiError

from app.client import create_square_client
from app.order_inventory_projection import (
    combine_projected_usage,
    project_line_item_usage,
)


def _extract_line_items(order):
    extracted = []

    for line_item in order.line_items or []:
        if not line_item.catalog_object_id:
            continue

        extracted.append(
            {
                "order_id": order.id,
                "sold_variation_id": line_item.catalog_object_id,
                "quantity": line_item.quantity,
                "name": line_item.name,
            }
        )

    return extracted


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: ./.venv/bin/python -m scripts.project_completed_orders_batch "
            "<order_id> [<order_id> ...]"
        )
        return 1

    client = create_square_client()
    processed_orders = []
    skipped_orders = []
    skipped_line_items = []
    projected_line_items = []

    for order_id in sys.argv[1:]:
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

        extracted_line_items = _extract_line_items(order)
        processed_orders.append(
            {
                "order_id": order.id,
                "state": order.state,
                "line_item_count": len(extracted_line_items),
            }
        )

        for line_item in extracted_line_items:
            try:
                projected_line_items.append(
                    project_line_item_usage(
                        line_item["sold_variation_id"],
                        line_item["quantity"],
                    )
                )
            except Exception as error:
                skipped_line_items.append(
                    {
                        **line_item,
                        "reason": str(error),
                    }
                )

    combined_usage = combine_projected_usage(projected_line_items)

    print("processed_orders:")
    print(json.dumps(processed_orders, indent=2))
    print("skipped_orders:")
    print(json.dumps(skipped_orders, indent=2))
    print("skipped_line_items:")
    print(json.dumps(skipped_line_items, indent=2))
    print("projected_line_items:")
    print(json.dumps(projected_line_items, indent=2))
    print("combined_usage:")
    print(json.dumps(combined_usage, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
