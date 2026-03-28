import unittest

from scripts.apply_inventory_adjustments import _build_adjustment_changes


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
