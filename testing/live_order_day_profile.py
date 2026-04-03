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


def _normalize_non_negative_decimal(value, name):
    normalized = Decimal(str(value))
    if normalized < 0:
        raise ValueError(f"{name} cannot be negative. Got: {value}")
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


def _count_profile_orders(profile):
    return sum(_normalize_count(entry["order_count"]) for entry in profile.get("entries", []))


def list_day_profiles():
    return [
        summarize_day_profile(profile_name, include_projected_usage=False)
        for profile_name in sorted(_load_profiles())
    ]


def _resolve_planning_entries(profile_name, profile, scenarios):
    planning_entries = []
    for entry in profile.get("entries", []):
        scenario_name = entry["scenario_name"]
        scenario = scenarios.get(scenario_name)
        if not scenario:
            raise ValueError(
                f"Profile '{profile_name}' references unknown scenario '{scenario_name}'."
            )

        planning_entries.append(
            {
                "scenario_name": scenario_name,
                "scenario": scenario,
                "remaining_orders": _normalize_count(entry["order_count"]),
                "burst_size": _normalize_count(entry.get("burst_size", 1)),
                "drink_count": count_scenario_drinks(scenario),
            }
        )

    return planning_entries


def _build_interleaved_day_profile_orders(
    profile_name,
    location_id,
    planning_entries,
    limit=None,
):
    planned_orders = []
    sequence = 1

    while any(entry["remaining_orders"] > 0 for entry in planning_entries):
        for entry in planning_entries:
            if entry["remaining_orders"] <= 0:
                continue

            burst_count = min(entry["burst_size"], entry["remaining_orders"])
            for _ in range(burst_count):
                if limit is not None and len(planned_orders) >= limit:
                    return planned_orders

                reference_context = (
                    f"{profile_name}-{sequence:03d}-{entry['scenario_name']}"
                )
                planned_orders.append(
                    {
                        "sequence": sequence,
                        "scenario_name": entry["scenario_name"],
                        "scenario_description": entry["scenario"].get("description", ""),
                        "drink_count": entry["drink_count"],
                        "order_payload": _build_order_payload(
                            location_id,
                            reference_context,
                            entry["scenario"],
                        ),
                    }
                )
                sequence += 1
                entry["remaining_orders"] -= 1

    return planned_orders


def _build_grouped_day_profile_orders(
    profile_name,
    location_id,
    planning_entries,
    limit=None,
):
    planned_orders = []
    sequence = 1

    for entry in planning_entries:
        while entry["remaining_orders"] > 0:
            if limit is not None and len(planned_orders) >= limit:
                return planned_orders

            reference_context = f"{profile_name}-{sequence:03d}-{entry['scenario_name']}"
            planned_orders.append(
                {
                    "sequence": sequence,
                    "scenario_name": entry["scenario_name"],
                    "scenario_description": entry["scenario"].get("description", ""),
                    "drink_count": entry["drink_count"],
                    "order_payload": _build_order_payload(
                        location_id,
                        reference_context,
                        entry["scenario"],
                    ),
                }
            )
            sequence += 1
            entry["remaining_orders"] -= 1

    return planned_orders


def build_day_profile_orders(profile_name, limit=None, offset=0):
    scenario_data = _load_scenarios()
    scenarios = scenario_data.get("scenarios", {})
    location_id = scenario_data["location_id"]
    profile = get_day_profile(profile_name)

    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive when provided")
    if offset < 0:
        raise ValueError("offset cannot be negative")

    planning_entries = _resolve_planning_entries(profile_name, profile, scenarios)
    ordering_strategy = profile.get("ordering_strategy", "grouped")
    builders = {
        "grouped": _build_grouped_day_profile_orders,
        "interleaved": _build_interleaved_day_profile_orders,
    }
    builder = builders.get(ordering_strategy)
    if builder is None:
        raise ValueError(
            f"Unsupported ordering_strategy '{ordering_strategy}' for profile '{profile_name}'."
        )

    planned_orders = builder(
        profile_name,
        location_id,
        planning_entries,
        None if limit is None else limit + offset,
    )
    return planned_orders[offset : None if limit is None else offset + limit]


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


def project_day_profile_usage(profile_name, limit=None, offset=0):
    projected_line_items = []
    for planned_order in build_day_profile_orders(
        profile_name,
        limit=limit,
        offset=offset,
    ):
        projected_line_items.extend(_project_payload_usage(planned_order["order_payload"]))

    combined_usage = combine_projected_usage(projected_line_items)
    return sorted(
        combined_usage,
        key=lambda usage: (
            -Decimal(str(usage["total_amount"])),
            usage["inventory_key"],
        ),
    )


def summarize_day_profile(
    profile_name,
    limit=None,
    offset=0,
    include_projected_usage=True,
):
    profile = get_day_profile(profile_name)
    planned_orders = build_day_profile_orders(profile_name, limit=limit, offset=offset)

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
        "ordering_strategy": profile.get("ordering_strategy", "grouped"),
        "offset": offset,
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
            offset=offset,
        )

    return summary


def build_operational_drill_commands(profile_name):
    profile = get_day_profile(profile_name)
    batches = profile.get("drill_batches", [])
    if not batches:
        raise ValueError(f"Profile '{profile_name}' does not define drill_batches.")
    dispatch_offsets_minutes = profile.get("dispatch_offsets_minutes")
    if dispatch_offsets_minutes and len(dispatch_offsets_minutes) != len(batches):
        raise ValueError(
            f"Profile '{profile_name}' must define dispatch_offsets_minutes for each drill batch."
        )
    if sum(_normalize_count(batch_size) for batch_size in batches) != _count_profile_orders(profile):
        raise ValueError(
            f"Profile '{profile_name}' drill_batches must sum to the total planned order count."
        )

    commands = []
    offset = 0
    previous_dispatch_offset = Decimal("0")
    for index, batch_size in enumerate(batches):
        normalized_batch_size = _normalize_count(batch_size)
        dispatch_offset_minutes = (
            _normalize_non_negative_decimal(dispatch_offsets_minutes[index], "dispatch offset")
            if dispatch_offsets_minutes
            else previous_dispatch_offset
        )
        wait_since_previous_minutes = (
            dispatch_offset_minutes - previous_dispatch_offset
            if index > 0
            else Decimal("0")
        )
        commands.append(
            {
                "action": "pay_batch",
                "batch_number": index + 1,
                "offset": offset,
                "limit": normalized_batch_size,
                "dispatch_offset_minutes": str(dispatch_offset_minutes),
                "wait_since_previous_minutes": str(wait_since_previous_minutes),
                "command": (
                    "./.venv/bin/python -m testing.run_live_order_day_profile "
                    f"--pay --offset {offset} --limit {normalized_batch_size} {profile_name}"
                ),
            }
        )
        commands.append(
            {
                "action": "check_main_queue",
                "after_batch_offset": offset,
                "command": (
                    "aws --no-cli-pager sqs get-queue-attributes "
                    "--queue-url https://sqs.us-west-2.amazonaws.com/541341197059/mosa-tea-webhook-jobs "
                    "--attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible"
                ),
            }
        )
        commands.append(
            {
                "action": "check_dlq",
                "after_batch_offset": offset,
                "command": (
                    "aws --no-cli-pager sqs get-queue-attributes "
                    "--queue-url https://sqs.us-west-2.amazonaws.com/541341197059/mosa-tea-webhook-jobs-dlq "
                    "--attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible"
                ),
            }
        )
        offset += normalized_batch_size
        previous_dispatch_offset = dispatch_offset_minutes

    commands.append(
        {
            "action": "tail_worker_logs",
            "command": "aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-worker --since 15m",
        }
    )
    commands.append(
        {
            "action": "tail_ingress_logs",
            "command": "aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-ingress --since 15m",
        }
    )
    return commands


def build_dispatch_schedule(profile_name, schedule_scale=1):
    profile = get_day_profile(profile_name)
    batches = profile.get("drill_batches", [])
    dispatch_offsets_minutes = profile.get("dispatch_offsets_minutes", [])

    if not batches:
        raise ValueError(f"Profile '{profile_name}' does not define drill_batches.")
    if len(dispatch_offsets_minutes) != len(batches):
        raise ValueError(
            f"Profile '{profile_name}' must define dispatch_offsets_minutes for each drill batch."
        )
    if sum(_normalize_count(batch_size) for batch_size in batches) != _count_profile_orders(profile):
        raise ValueError(
            f"Profile '{profile_name}' drill_batches must sum to the total planned order count."
        )

    scale = _normalize_non_negative_decimal(schedule_scale, "schedule scale")
    schedule = []
    offset = 0
    previous_dispatch_offset = Decimal("0")

    for index, batch_size in enumerate(batches):
        normalized_batch_size = _normalize_count(batch_size)
        dispatch_offset_minutes = _normalize_non_negative_decimal(
            dispatch_offsets_minutes[index],
            "dispatch offset",
        )
        if index > 0 and dispatch_offset_minutes < previous_dispatch_offset:
            raise ValueError(
                f"Profile '{profile_name}' has non-monotonic dispatch_offsets_minutes."
            )

        wait_minutes = (
            dispatch_offset_minutes - previous_dispatch_offset
            if index > 0
            else Decimal("0")
        )
        schedule.append(
            {
                "batch_number": index + 1,
                "offset": offset,
                "limit": normalized_batch_size,
                "dispatch_offset_minutes": str(dispatch_offset_minutes),
                "wait_since_previous_minutes": str(wait_minutes),
                "sleep_before_seconds": str(wait_minutes * Decimal("60") * scale),
            }
        )
        offset += normalized_batch_size
        previous_dispatch_offset = dispatch_offset_minutes

    return schedule
