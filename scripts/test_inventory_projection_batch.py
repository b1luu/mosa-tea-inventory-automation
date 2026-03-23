import json
import sys

from app.order_inventory_projection import (
    combine_projected_usage,
    project_line_item_usage,
)


def _parse_line_item_argument(argument):
    try:
        sold_variation_id, quantity = argument.split(":", maxsplit=1)
    except ValueError as error:
        raise ValueError(
            "Each argument must use the format <sold_variation_id>:<quantity>."
        ) from error

    return sold_variation_id, quantity


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: ./.venv/bin/python -m scripts.test_inventory_projection_batch "
            "<sold_variation_id:quantity> [<sold_variation_id:quantity> ...]"
        )
        return 1

    try:
        projected_line_items = [
            project_line_item_usage(*_parse_line_item_argument(argument))
            for argument in sys.argv[1:]
        ]
        combined_usage = combine_projected_usage(projected_line_items)
    except Exception as error:
        print(f"Projection error: {error}")
        return 1

    print("projected_line_items:")
    print(json.dumps(projected_line_items, indent=2))
    print("combined_usage:")
    print(json.dumps(combined_usage, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
