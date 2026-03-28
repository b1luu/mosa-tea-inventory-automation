import unittest

from app.inventory_stock_units import (
    convert_inventory_amount_to_stock_unit,
    summarize_combined_usage_in_display_units,
)


class InventoryStockUnitTests(unittest.TestCase):
    def test_tgy_converts_grams_to_bags(self):
        converted = convert_inventory_amount_to_stock_unit("tgy", 73800)
        self.assertEqual(converted["stock_unit"], "bag")
        self.assertEqual(converted["stock_unit_amount"], 123.0)

    def test_display_usage_converts_only_items_with_stock_metadata(self):
        summarized = summarize_combined_usage_in_display_units(
            [
                {
                    "inventory_key": "tgy",
                    "inventory_unit": "g",
                    "total_amount": 600,
                },
                {
                    "inventory_key": "milk",
                    "inventory_unit": "ml",
                    "total_amount": 150,
                },
            ]
        )
        self.assertEqual(summarized[0]["display_unit"], "bag")
        self.assertEqual(summarized[0]["display_amount"], 1.0)
        self.assertEqual(summarized[1]["display_unit"], "ml")
        self.assertEqual(summarized[1]["display_amount"], 150)


if __name__ == "__main__":
    unittest.main()
