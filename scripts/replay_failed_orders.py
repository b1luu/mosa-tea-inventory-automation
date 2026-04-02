import json

from app.json_utils import to_jsonable
from app.order_processing_store import PROCESSING_STATE_FAILED, list_order_processing_rows
from app.order_processor import process_orders


def _print_result(order_id, result):
    print("replay_result:")
    print(
        json.dumps(
            to_jsonable(
                {
                "order_id": order_id,
                "mode": result["mode"],
                "projected_orders": result["projected_orders"],
                "skipped_orders": result["skipped_orders"],
                "skipped_line_items": result["skipped_line_items"],
                "combined_usage": result["combined_usage"],
                "display_usage": result["display_usage"],
                "inventory_request": result["inventory_request"],
                "inventory_response": result["inventory_response"],
                }
            ),
            indent=2,
        )
    )


def main():
    failed_rows = list_order_processing_rows(processing_state=PROCESSING_STATE_FAILED)
    failed_order_ids = [row["square_order_id"] for row in failed_rows]

    print("failed_order_ids:")
    print(json.dumps(failed_order_ids, indent=2))

    if not failed_order_ids:
        return 0

    exit_code = 0
    for order_id in failed_order_ids:
        result = process_orders([order_id], apply_changes=True)
        _print_result(order_id, result)
        inventory_response = result["inventory_response"] or {}
        if "error" in inventory_response:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
