import json
import sys

from app.json_utils import to_jsonable
from app.order_processor import process_orders


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


def _print_result(result):
    print("mode:")
    print(json.dumps(to_jsonable(result["mode"]), indent=2))
    print("projected_orders:")
    print(json.dumps(to_jsonable(result["projected_orders"]), indent=2))
    print("skipped_orders:")
    print(json.dumps(to_jsonable(result["skipped_orders"]), indent=2))
    print("skipped_line_items:")
    print(json.dumps(to_jsonable(result["skipped_line_items"]), indent=2))
    print("projected_line_items:")
    print(json.dumps(to_jsonable(result["projected_line_items"]), indent=2))
    print("combined_usage:")
    print(json.dumps(to_jsonable(result["combined_usage"]), indent=2))
    print("display_usage:")
    print(json.dumps(to_jsonable(result["display_usage"]), indent=2))
    print("inventory_request:")
    print(json.dumps(to_jsonable(result["inventory_request"]), indent=2))

    if result["inventory_response"] is not None:
        print("inventory_response:")
        print(json.dumps(to_jsonable(result["inventory_response"]), indent=2))


def main():
    try:
        apply_changes, order_ids = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    result = process_orders(order_ids, apply_changes=apply_changes)
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
