import unittest
from decimal import Decimal

from testing.order_projection_utils import (
    load_fixture_order,
    load_scenario_order,
    project_order_summary,
    usage_by_inventory_key,
)


class OrderProjectionUtilsTests(unittest.TestCase):
    def assertEqual(self, first, second, msg=None):
        if isinstance(first, (Decimal, int, float)) and isinstance(
            second, (Decimal, int, float)
        ):
            return self.assertAlmostEqual(first, second, places=12, msg=msg)
        return super().assertEqual(first, second, msg=msg)

    def assertAlmostEqual(self, first, second, places=None, msg=None, delta=None):
        if isinstance(first, Decimal) or isinstance(second, Decimal):
            first = Decimal(str(first))
            second = Decimal(str(second))
            if delta is not None:
                delta = Decimal(str(delta))
        return super().assertAlmostEqual(
            first,
            second,
            places=places,
            msg=msg,
            delta=delta,
        )

    def test_load_fixture_order_accepts_name_without_extension(self):
        order_fixture = load_fixture_order("completed_fresh_fruit_tea_green")

        self.assertEqual(order_fixture["id"], "fixture-fresh-fruit-tea-green")
        self.assertEqual(order_fixture["state"], "COMPLETED")

    def test_project_fixture_order_keeps_atomic_single_order_math(self):
        order_fixture = load_fixture_order("completed_fresh_fruit_tea_green")

        projected_line_items, combined_usage = project_order_summary(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "fresh_fruit_tea")

        combined_by_key = usage_by_inventory_key(combined_usage)
        self.assertEqual(combined_by_key["green_tea"], Decimal("8"))
        self.assertEqual(combined_by_key["u600_cup"], Decimal("1"))
        self.assertEqual(combined_by_key["small_straw"], Decimal("1"))

    def test_project_scenario_order_uses_same_atomic_projection_path(self):
        scenario_order = load_scenario_order("tgy_tea_100_sugar")

        projected_line_items, combined_usage = project_order_summary(scenario_order)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "tie_guan_yin_brewed_tea")

        combined_by_key = usage_by_inventory_key(combined_usage)
        self.assertEqual(combined_by_key["tgy"], Decimal("8"))
        self.assertEqual(combined_by_key["u600_cup"], Decimal("1"))
        self.assertEqual(combined_by_key["small_straw"], Decimal("1"))
