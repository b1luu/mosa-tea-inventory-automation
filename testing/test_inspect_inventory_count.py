import unittest
from decimal import Decimal
from types import SimpleNamespace

from scripts.inspect_inventory_count import (
    _resolve_target,
    build_projected_adjustment_summary,
    summarize_inventory_counts,
)
from testing.order_projection_utils import load_scenario_order, project_order_summary


class InspectInventoryCountTests(unittest.TestCase):
    def test_resolve_target_from_inventory_key(self):
        target = _resolve_target(inventory_key="tgy")

        self.assertEqual(target["inventory_key"], "tgy")
        self.assertEqual(target["catalog_object_id"], "DFSCYEJEFN4PTIKTE4YVJWLH")
        self.assertEqual(target["display_unit"], "bag")
        self.assertEqual(target["inventory_unit"], "g")

    def test_summarize_inventory_counts_defaults_missing_states_to_zero(self):
        target = _resolve_target(inventory_key="tgy")
        counts = [
            SimpleNamespace(
                catalog_object_id=target["catalog_object_id"],
                location_id="LB1MECVA7EZ8Z",
                state="IN_STOCK",
                quantity="122.858",
                calculated_at="2026-04-03T16:00:00Z",
            )
        ]

        summary = summarize_inventory_counts(target, counts, "LB1MECVA7EZ8Z")

        self.assertEqual(summary["in_stock_quantity"], Decimal("122.858"))
        self.assertEqual(summary["waste_quantity"], Decimal("0"))
        self.assertEqual(summary["states"]["WASTE"]["calculated_at"], None)

    def test_summarize_inventory_counts_tracks_waste_state_when_present(self):
        target = _resolve_target(inventory_key="tgy")
        counts = [
            SimpleNamespace(
                catalog_object_id=target["catalog_object_id"],
                location_id="LB1MECVA7EZ8Z",
                state="IN_STOCK",
                quantity="122.84467",
                calculated_at="2026-04-03T16:05:00Z",
            ),
            SimpleNamespace(
                catalog_object_id=target["catalog_object_id"],
                location_id="LB1MECVA7EZ8Z",
                state="WASTE",
                quantity="0.01333",
                calculated_at="2026-04-03T16:05:00Z",
            ),
        ]

        summary = summarize_inventory_counts(target, counts, "LB1MECVA7EZ8Z")

        self.assertEqual(summary["in_stock_quantity"], Decimal("122.84467"))
        self.assertEqual(summary["waste_quantity"], Decimal("0.01333"))

    def test_build_projected_adjustment_summary_shows_before_and_after(self):
        target = _resolve_target(inventory_key="tgy")
        counts = [
            SimpleNamespace(
                catalog_object_id=target["catalog_object_id"],
                location_id="LB1MECVA7EZ8Z",
                state="IN_STOCK",
                quantity="122.85777",
                calculated_at="2026-04-03T16:05:00Z",
            ),
            SimpleNamespace(
                catalog_object_id=target["catalog_object_id"],
                location_id="LB1MECVA7EZ8Z",
                state="WASTE",
                quantity="0.14223",
                calculated_at="2026-04-03T16:05:00Z",
            ),
        ]
        scenario_order = load_scenario_order("tgy_tea_100_sugar")
        _, combined_usage = project_order_summary(scenario_order)
        base_summary = summarize_inventory_counts(target, counts, "LB1MECVA7EZ8Z")

        projected_adjustment = build_projected_adjustment_summary(
            target,
            combined_usage,
            base_summary,
            {"kind": "scenario", "name": "tgy_tea_100_sugar"},
        )

        self.assertEqual(
            projected_adjustment["adjustment_quantity"],
            Decimal("0.01333"),
        )
        self.assertEqual(
            projected_adjustment["before"]["in_stock_quantity"],
            Decimal("122.85777"),
        )
        self.assertEqual(
            projected_adjustment["after"]["in_stock_quantity"],
            Decimal("122.84444"),
        )
        self.assertEqual(
            projected_adjustment["after"]["waste_quantity"],
            Decimal("0.15556"),
        )
