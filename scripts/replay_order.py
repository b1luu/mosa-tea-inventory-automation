import json
import sys

from app.json_utils import to_jsonable
from app.webhook_worker import replay_order_job


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.replay_order "
        "<order_id> [<order_id> ...]"
    )


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
    order_ids = sys.argv[1:]
    if not order_ids:
        print(_usage())
        return 1

    exit_code = 0
    for order_id in order_ids:
        try:
            result = replay_order_job(order_id)
        except RuntimeError as error:
            print(json.dumps({"order_id": order_id, "error": str(error)}, indent=2))
            exit_code = 1
            continue

        _print_result(result)

        inventory_response = result["inventory_response"] or {}
        if "error" in inventory_response:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
