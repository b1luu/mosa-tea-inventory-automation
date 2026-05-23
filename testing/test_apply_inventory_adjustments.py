import sys
import unittest
from unittest.mock import patch

from app.order_processor import _build_adjustment_changes
from scripts import apply_inventory_adjustments


class ApplyInventoryAdjustmentsMainTests(unittest.TestCase):
    def test_main_passes_an_explicit_client_to_process_orders(self):
        # The script must supply an explicit (env-token) client so its writes
        # opt in deliberately, rather than relying on a fallback that Part 3
        # removed. Without this, process_orders(apply_changes=True) would raise.
        empty_result = {
            "mode": {"apply": True},
            "projected_orders": [],
            "skipped_orders": [],
            "skipped_line_items": [],
            "projected_line_items": [],
            "combined_usage": [],
            "display_usage": [],
            "inventory_request": {},
            "inventory_response": {"ok": True},
        }
        with (
            patch.object(sys, "argv", ["prog", "--apply", "order-1"]),
            patch.object(
                apply_inventory_adjustments,
                "create_square_client",
                return_value="explicit-client",
            ),
            patch.object(
                apply_inventory_adjustments,
                "process_orders",
                return_value=empty_result,
            ) as mock_process,
        ):
            apply_inventory_adjustments.main()

        _, kwargs = mock_process.call_args
        self.assertEqual(kwargs["apply_changes"], True)
        self.assertEqual(kwargs["client"], "explicit-client")
        self.assertIsNotNone(kwargs["client"])


class ApplyInventoryAdjustmentsTests(unittest.TestCase):
    def test_build_adjustment_changes_uses_stock_units(self):
        changes = _build_adjustment_changes(
            ["order-1"],
            [
                {
                    "location_id": "LB1MECVA7EZ8Z",
                    "inventory_key": "4s",
                    "square_variation_id": "45IPVSWXHIMM3P535VAEPQFM",
                    "inventory_unit": "g",
                    "total_amount": 5.333333333333333,
                },
                {
                    "location_id": "LB1MECVA7EZ8Z",
                    "inventory_key": "milk",
                    "square_variation_id": "4CLJVUZQCIVAEU4F7APU6QGX",
                    "inventory_unit": "ml",
                    "total_amount": 150.0,
                },
            ],
            "2026-03-28T23:13:42.944017Z",
        )

        self.assertEqual(changes[0]["adjustment"]["quantity"], "0.00889")
        self.assertEqual(changes[1]["adjustment"]["quantity"], "0.03968")


if __name__ == "__main__":
    unittest.main()
