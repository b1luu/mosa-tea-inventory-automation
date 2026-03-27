import json
import sys

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


def _parse_args(argv):
    state_filter = "COMPLETED"
    limit = 20
    all_pages = False
    order_id_filter = None

    for arg in argv:
        upper_arg = arg.upper()
        if upper_arg in {"OPEN", "COMPLETED", "CANCELED", "DRAFT"}:
            state_filter = upper_arg
            continue

        if arg == "--all":
            all_pages = True
            continue

        if arg.startswith("--limit="):
            limit = int(arg.split("=", 1)[1])
            continue

        if arg.startswith("--order-id="):
            order_id_filter = arg.split("=", 1)[1]
            continue

        raise ValueError(
            "Usage: ./.venv/bin/python -m scripts.search_orders "
            "[STATE] [--limit=N] [--all] [--order-id=ORDER_ID]"
        )

    return state_filter, limit, all_pages, order_id_filter


def main():
    try:
        state_filter, limit, all_pages, order_id_filter = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

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

        orders = []
        cursor = None

        while True:
            response = client.orders.search(
                location_ids=location_ids,
                cursor=cursor,
                query={
                    "filter": {
                        "state_filter": {
                            "states": [state_filter]
                        }
                    },
                    "sort": {
                        "sort_field": "UPDATED_AT",
                        "sort_order": "DESC",
                    },
                },
                limit=limit,
            )
            orders.extend(response.orders or [])
            cursor = response.cursor

            if not all_pages or not cursor:
                break
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    if order_id_filter:
        orders = [order for order in orders if order.id == order_id_filter]

    print("search_summary:")
    print(
        json.dumps(
            {
                "state": state_filter,
                "limit_per_page": limit,
                "all_pages": all_pages,
                "order_id_filter": order_id_filter,
                "returned_order_count": len(orders),
                "has_more": bool(cursor),
                "next_cursor": cursor,
            },
            indent=2,
        )
    )
    print("orders:")
    print(json.dumps([summarize_order(order) for order in orders], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
