import json

from square.core.api_error import ApiError

from app.client import create_square_client


def summarize_order(order):
    return {
        "id": order.id,
        "location_id": order.location_id,
        "state": order.state,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "line_item_count": len(order.line_items or []),
    }


def main():
    client = create_square_client()

    try:
        locations_response = client.locations.list()
        location_ids = [
            location.id for location in (locations_response.locations or [])
            if location.id
        ]

        if not location_ids:
            print("No locations found for this merchant.")
            return 1

        response = client.orders.search(
            location_ids=location_ids,
            query={
                "filter": {
                    "state_filter": {
                        "states": ["OPEN", "COMPLETED"]
                    }
                },
                "sort": {
                    "sort_field": "UPDATED_AT",
                    "sort_order": "DESC",
                },
            },
            limit=20,
        )
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    orders = response.orders or []
    print(json.dumps([summarize_order(order) for order in orders], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
