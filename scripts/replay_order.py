import json
import sys

from app.order_processor import process_orders


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.replay_order "
        "<order_id> [<order_id> ...]"
    )


def _print_result(result):
    print("mode:")
    print(json.dumps(result["mode"], indent=2))
    print("projected_orders:")
    print(json.dumps(result["projected_orders"], indent=2))
    print("skipped_orders:")
    print(json.dumps(result["skipped_orders"], indent=2))
    print("skipped_line_items:")
    print(json.dumps(result["skipped_line_items"], indent=2))
    print("projected_line_items:")
    print(json.dumps(result["projected_line_items"], indent=2))
    print("combined_usage:")
    print(json.dumps(result["combined_usage"], indent=2))
    print("display_usage:")
    print(json.dumps(result["display_usage"], indent=2))
    print("inventory_request:")
    print(json.dumps(result["inventory_request"], indent=2))

    if result["inventory_response"] is not None:
        print("inventory_response:")
        print(json.dumps(result["inventory_response"], indent=2))


def main():
    order_ids = sys.argv[1:]
    if not order_ids:
        print(_usage())
        return 1

    result = process_orders(order_ids, apply_changes=True)
    _print_result(result)

    inventory_response = result["inventory_response"] or {}
    if "error" in inventory_response:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
