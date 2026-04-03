import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from app.order_inventory_projection import (
    combine_projected_usage,
    project_line_item_usage,
)
from testing.create_live_test_order import _build_order_payload, _load_scenarios


PROFILE_FILE = Path("testing/live_order_day_profiles.json")


def _load_profiles():
    return json.loads(PROFILE_FILE.read_text(encoding="utf-8")).get("profiles", {})


def _normalize_count(value):
    normalized = int(Decimal(str(value)))
    if normalized <= 0:
        raise ValueError(f"Profile count must be positive. Got: {value}")
    return normalized


def count_scenario_drinks(scenario):
    return sum(
        _normalize_count(line_item["quantity"])
        for line_item in scenario.get("line_items", [])
    )


def get_day_profile(profile_name):
    profile = _load_profiles().get(profile_name)
    if not profile:
        raise ValueError(f"Unknown live day profile: {profile_name}")
    return profile


def list_day_profiles():
    return [
        summarize_day_profile(profile_name, include_projected_usage=False)
        for profile_name in sorted(_load_profiles())
    ]


def build_day_profile_orders(profile_name, limit=None):
    scenario_data = _load_scenarios()
    scenarios = scenario_data.get("scenarios", {})
    location_id = scenario_data["location_id"]
    profile = get_day_profile(profile_name)

    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive when provided")

    planned_orders = []
    sequence = 1
    for entry in profile.get("entries", []):
        scenario_name = entry["scenario_name"]
        scenario = scenarios.get(scenario_name)
        if not scenario:
            raise ValueError(
                f"Profile '{profile_name}' references unknown scenario '{scenario_name}'."
            )

        order_count = _normalize_count(entry["order_count"])
        drink_count = count_scenario_drinks(scenario)
        for _ in range(order_count):
            if limit is not None and len(planned_orders) >= limit:
                return planned_orders

            reference_context = f"{profile_name}-{sequence:03d}-{scenario_name}"
            planned_orders.append(
                {
                    "sequence": sequence,
                    "scenario_name": scenario_name,
                    "scenario_description": scenario.get("description", ""),
                    "drink_count": drink_count,
                    "order_payload": _build_order_payload(
                        location_id,
                        reference_context,
                        scenario,
                    ),
                }
            )
            sequence += 1

    return planned_orders


def _project_payload_usage(order_payload):
    projected_line_items = []
    for line_item in order_payload.get("line_items", []):
        modifier_ids = [
            modifier["catalog_object_id"]
            for modifier in line_item.get("modifiers", [])
            if modifier.get("catalog_object_id")
        ]
        projected_line_items.append(
            project_line_item_usage(
                line_item["catalog_object_id"],
                line_item["quantity"],
                modifier_ids,
            )
        )

    return projected_line_items


def project_day_profile_usage(profile_name, limit=None):
    projected_line_items = []
    for planned_order in build_day_profile_orders(profile_name, limit=limit):
        projected_line_items.extend(_project_payload_usage(planned_order["order_payload"]))

    combined_usage = combine_projected_usage(projected_line_items)
    return sorted(
        combined_usage,
        key=lambda usage: (
            -Decimal(str(usage["total_amount"])),
            usage["inventory_key"],
        ),
    )


def summarize_day_profile(profile_name, limit=None, include_projected_usage=True):
    profile = get_day_profile(profile_name)
    planned_orders = build_day_profile_orders(profile_name, limit=limit)

    scenario_breakdown = defaultdict(
        lambda: {
            "scenario_name": "",
            "scenario_description": "",
            "order_count": 0,
            "drinks_per_order": 0,
            "total_drinks": 0,
        }
    )

    for planned_order in planned_orders:
        scenario_name = planned_order["scenario_name"]
        breakdown = scenario_breakdown[scenario_name]
        breakdown["scenario_name"] = scenario_name
        breakdown["scenario_description"] = planned_order["scenario_description"]
        breakdown["drinks_per_order"] = planned_order["drink_count"]
        breakdown["order_count"] += 1
        breakdown["total_drinks"] += planned_order["drink_count"]

    summary = {
        "profile_name": profile_name,
        "description": profile.get("description", ""),
        "total_orders": len(planned_orders),
        "total_drinks": sum(order["drink_count"] for order in planned_orders),
        "scenario_breakdown": sorted(
            scenario_breakdown.values(),
            key=lambda item: (-item["total_drinks"], item["scenario_name"]),
        ),
    }

    if include_projected_usage:
        summary["projected_inventory_usage"] = project_day_profile_usage(
            profile_name,
            limit=limit,
        )

    return summary
