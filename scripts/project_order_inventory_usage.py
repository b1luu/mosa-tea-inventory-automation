import json
import sys

from square.core.api_error import ApiError

from app.client import create_square_client
from app.order_inventory_projection import (
    combine_projected_usage,
    project_line_item_usage,
)


def _extract_projectable_line_items(order):
    projectable_items = []

    for line_item in order.line_items or []:
        if not line_item.catalog_object_id:
            continue

        projectable_items.append(
            {
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

    return projectable_items


def main():
    if len(sys.argv) != 2:
        print(
            "Usage: ./.venv/bin/python -m scripts.project_order_inventory_usage "
            "<order_id>"
        )
        return 1

    order_id = sys.argv[1]
    client = create_square_client()

    try:
        response = client.orders.get(order_id=order_id)
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    if not response.order:
        print(f"Order not found: {order_id}")
        return 1

    projectable_line_items = _extract_projectable_line_items(response.order)

    try:
        projected_line_items = [
            project_line_item_usage(
                line_item["sold_variation_id"],
                line_item["quantity"],
                line_item["modifier_ids"],
            )
            for line_item in projectable_line_items
        ]
        combined_usage = combine_projected_usage(projected_line_items)
    except Exception as error:
        print(f"Projection error: {error}")
        return 1

    print("order_summary:")
    print(
        json.dumps(
            {
                "order_id": response.order.id,
                "state": response.order.state,
                "line_items": projectable_line_items,
            },
            indent=2,
        )
    )
    print("projected_line_items:")
    print(json.dumps(projected_line_items, indent=2))
    print("combined_usage:")
    print(json.dumps(combined_usage, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
