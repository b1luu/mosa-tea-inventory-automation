import json
import sys

from app.order_inventory_projection import project_line_item_usage


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: ./.venv/bin/python -m scripts.test_inventory_projection "
            "<sold_variation_id> <quantity>"
        )
        return 1

    sold_variation_id = sys.argv[1]
    quantity = sys.argv[2]

    try:
        projection = project_line_item_usage(sold_variation_id, quantity)
    except Exception as error:
        print(f"Projection error: {error}")
        return 1

    print(json.dumps(projection, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
