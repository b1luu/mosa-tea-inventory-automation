import json
import sys

from square.core.api_error import ApiError

from app.client import create_square_client


def summarize_line_item(line_item):
    return {
        "uid": line_item.uid,
        "name": line_item.name,
        "quantity": line_item.quantity,
        "catalog_object_id": line_item.catalog_object_id,
        "variation_name": line_item.variation_name,
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


def summarize_order(order):
    return {
        "id": order.id,
        "customer_id": getattr(order, "customer_id", None),
        "location_id": order.location_id,
        "ticket_name": getattr(order, "ticket_name", None),
        "state": order.state,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "fulfillments": [
            {
                "uid": fulfillment.uid,
                "type": fulfillment.type,
                "state": fulfillment.state,
                "pickup_details": {
                    "pickup_at": (
                        fulfillment.pickup_details.pickup_at
                        if getattr(fulfillment, "pickup_details", None)
                        else None
                    ),
                    "recipient": {
                        "customer_id": (
                            fulfillment.pickup_details.recipient.customer_id
                            if getattr(fulfillment, "pickup_details", None)
                            and getattr(fulfillment.pickup_details, "recipient", None)
                            else None
                        ),
                        "display_name": (
                            fulfillment.pickup_details.recipient.display_name
                            if getattr(fulfillment, "pickup_details", None)
                            and getattr(fulfillment.pickup_details, "recipient", None)
                            else None
                        ),
                    },
                }
                if getattr(fulfillment, "pickup_details", None)
                else None,
            }
            for fulfillment in (getattr(order, "fulfillments", None) or [])
        ],
        "line_items": [
            summarize_line_item(line_item)
            for line_item in (order.line_items or [])
        ],
    }


def main():
    if len(sys.argv) != 2:
        print("Usage: ./.venv/bin/python -m scripts.inspect_order <order_id>")
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

    print(json.dumps(summarize_order(response.order), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
