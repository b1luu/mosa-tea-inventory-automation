import json
import sys
import uuid
from pathlib import Path

from square.core.api_error import ApiError

from app.client import create_square_client
from scripts.inspect_order import summarize_order


SCENARIO_FILE = Path("testing/live_order_scenarios.json")


def _load_scenarios():
    return json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))


def _usage():
    return (
        "Usage: ./.venv/bin/python -m testing.create_live_test_order "
        "[--list] <scenario_name>"
    )


def _parse_args(argv):
    if not argv:
        raise ValueError(_usage())

    if argv == ["--list"]:
        return True, None

    if len(argv) != 1:
        raise ValueError(_usage())

    return False, argv[0]


def _build_order_payload(location_id, scenario_name, scenario):
    line_items = []

    for line_item in scenario.get("line_items", []):
        payload_line_item = {
            "catalog_object_id": line_item["catalog_object_id"],
            "quantity": line_item["quantity"],
        }

        modifiers = line_item.get("modifiers", [])
        if modifiers:
            payload_line_item["modifiers"] = [
                {
                    "catalog_object_id": modifier["catalog_object_id"],
                    "quantity": modifier.get("quantity", "1"),
                }
                for modifier in modifiers
            ]

        line_items.append(payload_line_item)

    return {
        "location_id": location_id,
        "reference_id": f"testing:{scenario_name}",
        "line_items": line_items,
    }


def main():
    try:
        list_only, scenario_name = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    scenario_data = _load_scenarios()
    location_id = scenario_data["location_id"]
    scenarios = scenario_data.get("scenarios", {})

    if list_only:
        print("available_scenarios:")
        print(
            json.dumps(
                {
                    name: scenario.get("description", "")
                    for name, scenario in scenarios.items()
                },
                indent=2,
            )
        )
        return 0

    scenario = scenarios.get(scenario_name)
    if not scenario:
        print(f"Unknown scenario: {scenario_name}")
        print(_usage())
        return 1

    client = create_square_client()
    order_payload = _build_order_payload(location_id, scenario_name, scenario)
    idempotency_key = str(uuid.uuid4())

    try:
        response = client.orders.create(
            order=order_payload,
            idempotency_key=idempotency_key,
        )
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    if not response.order:
        print("Order creation did not return an order.")
        return 1

    print("scenario:")
    print(json.dumps({"name": scenario_name}, indent=2))
    print("order_payload:")
    print(json.dumps(order_payload, indent=2))
    print("created_order:")
    print(json.dumps(summarize_order(response.order), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
