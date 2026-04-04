import json
from pathlib import Path

from app.inventory_plan import build_inventory_plan_from_order_summary
from scripts.inspect_order import summarize_order
from testing.create_live_test_order import _build_order_payload, _load_scenarios


FIXTURE_ORDER_DIR = Path("testing/fixtures/orders")


def normalize_fixture_name(fixture_name):
    return fixture_name if fixture_name.endswith(".json") else f"{fixture_name}.json"


def load_fixture_order(fixture_name):
    fixture_path = FIXTURE_ORDER_DIR / normalize_fixture_name(fixture_name)
    if not fixture_path.exists():
        raise ValueError(f"Unknown fixture order: {fixture_name}")
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def load_scenario_order(scenario_name):
    scenario_data = _load_scenarios()
    scenario = scenario_data.get("scenarios", {}).get(scenario_name)
    if not scenario:
        raise ValueError(f"Unknown scenario: {scenario_name}")

    order_payload = _build_order_payload(
        scenario_data["location_id"],
        scenario_name,
        scenario,
    )
    return {
        "id": None,
        "location_id": order_payload["location_id"],
        "state": None,
        "created_at": None,
        "updated_at": None,
        "reference_id": order_payload["reference_id"],
        "line_items": order_payload["line_items"],
    }


def summarize_live_order(order):
    return summarize_order(order)


def project_order_summary(order_summary):
    plan = build_inventory_plan_from_order_summary(order_summary)
    return plan.projected_line_items, plan.combined_usage


def usage_by_inventory_key(combined_usage):
    return {
        usage["inventory_key"]: usage["total_amount"]
        for usage in combined_usage
    }
