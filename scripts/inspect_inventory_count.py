import json
import sys
from decimal import Decimal
from pathlib import Path

from square.core.api_error import ApiError

from app.client import create_square_client
from app.inventory_stock_units import (
    convert_inventory_amount_to_stock_unit,
    has_stock_unit_mapping,
)
from app.json_utils import to_jsonable
from app.order_inventory_projection import load_inventory_item_map
from testing.order_projection_utils import (
    load_fixture_order,
    load_scenario_order,
    project_order_summary,
    summarize_live_order,
)


SCENARIO_FILE = Path("testing/live_order_scenarios.json")
DEFAULT_STATES = ("IN_STOCK", "WASTE")


def _load_default_location_id():
    scenario_data = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    return scenario_data["location_id"]


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.inspect_inventory_count "
        "(--inventory-key <inventory_key> | --catalog-object-id <catalog_object_id>) "
        "[--location-id <location_id>] "
        "[--fixture <fixture_name> | --scenario <scenario_name> | --order-id <order_id>]"
    )


def _parse_args(argv):
    inventory_key = None
    catalog_object_id = None
    location_id = None
    fixture_name = None
    scenario_name = None
    order_id = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--inventory-key":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            inventory_key = argv[i]
        elif arg == "--catalog-object-id":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            catalog_object_id = argv[i]
        elif arg == "--location-id":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            location_id = argv[i]
        elif arg == "--fixture":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            fixture_name = argv[i]
        elif arg == "--scenario":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            scenario_name = argv[i]
        elif arg == "--order-id":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            order_id = argv[i]
        else:
            raise ValueError(_usage())
        i += 1

    if bool(inventory_key) == bool(catalog_object_id):
        raise ValueError(_usage())
    if sum(bool(value) for value in (fixture_name, scenario_name, order_id)) > 1:
        raise ValueError(_usage())

    projection_source = None
    if fixture_name:
        projection_source = {"kind": "fixture", "name": fixture_name}
    elif scenario_name:
        projection_source = {"kind": "scenario", "name": scenario_name}
    elif order_id:
        projection_source = {"kind": "live_order", "name": order_id}

    return (
        inventory_key,
        catalog_object_id,
        location_id or _load_default_location_id(),
        projection_source,
    )


def _resolve_target(inventory_key=None, catalog_object_id=None):
    inventory_item_map = load_inventory_item_map()

    if inventory_key:
        inventory_item = inventory_item_map.get(inventory_key)
        if not inventory_item:
            raise ValueError(f"Unknown inventory key: {inventory_key}")

        return {
            "inventory_key": inventory_key,
            "catalog_object_id": inventory_item["square_variation_id"],
            "name": inventory_item.get("name"),
            "inventory_unit": inventory_item.get("unit"),
            "display_unit": (
                inventory_item.get("stock_unit")
                if has_stock_unit_mapping(inventory_key)
                else inventory_item.get("unit")
            ),
            "stock_unit_size": inventory_item.get("stock_unit_size"),
            "stock_unit_size_unit": inventory_item.get("stock_unit_size_unit"),
        }

    for key, inventory_item in inventory_item_map.items():
        if inventory_item.get("square_variation_id") != catalog_object_id:
            continue

        return {
            "inventory_key": key,
            "catalog_object_id": catalog_object_id,
            "name": inventory_item.get("name"),
            "inventory_unit": inventory_item.get("unit"),
            "display_unit": (
                inventory_item.get("stock_unit")
                if has_stock_unit_mapping(key)
                else inventory_item.get("unit")
            ),
            "stock_unit_size": inventory_item.get("stock_unit_size"),
            "stock_unit_size_unit": inventory_item.get("stock_unit_size_unit"),
        }

    return {
        "inventory_key": None,
        "catalog_object_id": catalog_object_id,
        "name": None,
        "inventory_unit": None,
        "display_unit": None,
        "stock_unit_size": None,
        "stock_unit_size_unit": None,
    }


def _state_name(state):
    if state is None:
        return None
    return state if isinstance(state, str) else str(state)


def _quantize_adjustment_quantity(quantity):
    return Decimal(str(quantity)).quantize(Decimal("0.00001"))


def _find_projected_usage_for_target(target, combined_usage):
    for usage in combined_usage:
        if target["inventory_key"] and usage.get("inventory_key") == target["inventory_key"]:
            return usage
        if usage.get("square_variation_id") == target["catalog_object_id"]:
            return usage
    return None


def build_projected_adjustment_summary(target, combined_usage, summary, source):
    matched_usage = _find_projected_usage_for_target(target, combined_usage)
    raw_inventory_amount = Decimal("0")
    raw_inventory_unit = target["inventory_unit"]
    adjustment_quantity = Decimal("0")
    adjustment_display_unit = target["display_unit"] or target["inventory_unit"]

    if matched_usage:
        raw_inventory_amount = Decimal(str(matched_usage["total_amount"]))
        raw_inventory_unit = matched_usage["inventory_unit"]
        if target["inventory_key"] and has_stock_unit_mapping(target["inventory_key"]):
            converted = convert_inventory_amount_to_stock_unit(
                target["inventory_key"],
                raw_inventory_amount,
            )
            adjustment_quantity = _quantize_adjustment_quantity(
                converted["stock_unit_amount"]
            )
            adjustment_display_unit = converted["stock_unit"]
        else:
            adjustment_quantity = _quantize_adjustment_quantity(raw_inventory_amount)

    before_in_stock = summary["in_stock_quantity"]
    before_waste = summary["waste_quantity"]

    return {
        "source": source,
        "raw_inventory_amount": raw_inventory_amount,
        "raw_inventory_unit": raw_inventory_unit,
        "adjustment_quantity": adjustment_quantity,
        "adjustment_display_unit": adjustment_display_unit,
        "before": {
            "in_stock_quantity": before_in_stock,
            "waste_quantity": before_waste,
        },
        "delta": {
            "in_stock_quantity": -adjustment_quantity,
            "waste_quantity": adjustment_quantity,
        },
        "after": {
            "in_stock_quantity": before_in_stock - adjustment_quantity,
            "waste_quantity": before_waste + adjustment_quantity,
        },
    }


def summarize_inventory_counts(target, counts, location_id, projected_adjustment=None):
    summary = {
        "inventory_key": target["inventory_key"],
        "catalog_object_id": target["catalog_object_id"],
        "location_id": location_id,
        "display_unit": target["display_unit"],
        "inventory_unit": target["inventory_unit"],
        "states": {},
    }

    for state in DEFAULT_STATES:
        summary["states"][state] = {
            "quantity": Decimal("0"),
            "calculated_at": None,
        }

    for count in counts:
        state = _state_name(getattr(count, "state", None))
        if state not in summary["states"]:
            summary["states"][state] = {
                "quantity": Decimal("0"),
                "calculated_at": None,
            }

        quantity = Decimal(str(getattr(count, "quantity", "0")))
        calculated_at = getattr(count, "calculated_at", None)
        summary["states"][state] = {
            "quantity": quantity,
            "calculated_at": calculated_at,
        }

    summary["in_stock_quantity"] = summary["states"]["IN_STOCK"]["quantity"]
    summary["waste_quantity"] = summary["states"]["WASTE"]["quantity"]
    if projected_adjustment is not None:
        summary["projected_adjustment"] = projected_adjustment
    return summary


def _load_projection_source(client, source):
    if source is None:
        return None, None

    if source["kind"] == "fixture":
        return source, load_fixture_order(source["name"])
    if source["kind"] == "scenario":
        return source, load_scenario_order(source["name"])

    try:
        response = client.orders.get(order_id=source["name"])
    except ApiError as error:
        raise ValueError(f"Square API error: {error}") from error

    if not response.order:
        raise ValueError(f"Order not found: {source['name']}")

    return source, summarize_live_order(response.order)


def main():
    try:
        inventory_key, catalog_object_id, location_id, projection_source = _parse_args(
            sys.argv[1:]
        )
        target = _resolve_target(inventory_key, catalog_object_id)
    except ValueError as error:
        print(error)
        return 1

    client = create_square_client()
    try:
        projection_source, projected_order = _load_projection_source(client, projection_source)
    except ValueError as error:
        print(error)
        return 1

    try:
        counts = list(
            client.inventory.batch_get_counts(
                catalog_object_ids=[target["catalog_object_id"]],
                location_ids=[location_id],
                states=list(DEFAULT_STATES),
            )
        )
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    projected_adjustment = None
    if projected_order is not None:
        _, combined_usage = project_order_summary(projected_order)
        base_summary = summarize_inventory_counts(target, counts, location_id)
        projected_adjustment = build_projected_adjustment_summary(
            target,
            combined_usage,
            base_summary,
            projection_source,
        )

    print("target:")
    print(
        json.dumps(
            to_jsonable(
                {
                    **target,
                    "location_id": location_id,
                }
            ),
            indent=2,
        )
    )
    print("counts:")
    print(
        json.dumps(
            to_jsonable(
                [
                    {
                        "catalog_object_id": count.catalog_object_id,
                        "location_id": count.location_id,
                        "state": _state_name(count.state),
                        "quantity": count.quantity,
                        "calculated_at": count.calculated_at,
                    }
                    for count in counts
                ]
            ),
            indent=2,
        )
    )
    print("summary:")
    print(
        json.dumps(
            to_jsonable(
                summarize_inventory_counts(
                    target,
                    counts,
                    location_id,
                    projected_adjustment=projected_adjustment,
                )
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
