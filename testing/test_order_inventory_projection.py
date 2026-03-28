import json
import unittest
from pathlib import Path

from app.order_inventory_projection import (
    combine_projected_usage,
    project_line_item_usage,
)


FIXTURE_DIR = Path("testing/fixtures/orders")


def load_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def project_fixture_order(order_fixture):
    projected_line_items = []

    for line_item in order_fixture.get("line_items", []):
        sold_variation_id = line_item.get("catalog_object_id")
        if not sold_variation_id:
            continue

        projected_line_items.append(
            project_line_item_usage(
                sold_variation_id,
                line_item["quantity"],
                [
                    modifier["catalog_object_id"]
                    for modifier in line_item.get("modifiers", [])
                    if modifier.get("catalog_object_id")
                ],
            )
        )

    return projected_line_items, combine_projected_usage(projected_line_items)


class OrderInventoryProjectionTests(unittest.TestCase):
    def test_real_completed_grapefruit_bloom_and_matcha_fixture(self):
        order_fixture = load_fixture("completed_grapefruit_bloom_matcha.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 2)

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["4s"], 6.0)
        self.assertEqual(combined_by_key["buckwheat"], 0.75)
        self.assertEqual(combined_by_key["barley"], 1.5)
        self.assertEqual(combined_by_key["matcha"], 17.5)
        self.assertAlmostEqual(combined_by_key["tgy"], 2.3255813953488373)
        self.assertAlmostEqual(combined_by_key["tj_powder"], 5.813953488372093)
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 3.488372093023256)
        self.assertAlmostEqual(combined_by_key["sugar_syrup"], 3.488372093023256)
        self.assertEqual(combined_by_key["u600_cup"], 3.0)
        self.assertEqual(combined_by_key["small_straw"], 2.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

    def test_tgy_special_fixture_includes_hun_kue(self):
        order_fixture = load_fixture("completed_tgy_special.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "tgy_special")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["tgy"], 8.0)
        self.assertAlmostEqual(combined_by_key["hk_powder"], 8.571428571428571)
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 3.4285714285714284)
        self.assertAlmostEqual(combined_by_key["brown_sugar"], 3.4285714285714284)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

    def test_taiwanese_retro_fixture_includes_boba(self):
        order_fixture = load_fixture("completed_taiwanese_retro.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "taiwanese_retro")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertAlmostEqual(combined_by_key["black_tea"], 4.666666666666667)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertEqual(combined_by_key["boba"], 100.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

    def test_simple_tgy_brewed_tea_fixture(self):
        order_fixture = load_fixture("completed_tgy_brewed_tea.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "tie_guan_yin_brewed_tea")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["tgy"], 8.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_tgy_osmanthus_honey_brewed_tea_fixture(self):
        order_fixture = load_fixture("completed_tgy_osmanthus_honey_brewed_tea.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(
            projected_line_items[0]["drink_key"],
            "tie_guan_yin_osmanthus_honey_brewed_tea",
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["tgy"], 8.0)
        self.assertEqual(combined_by_key["osmanthus_honey"], 35.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_modifier_aware_fresh_fruit_tea_fixture(self):
        order_fixture = load_fixture("completed_fresh_fruit_tea_four_seasons.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "fresh_fruit_tea")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["4s"], 8.0)
        self.assertEqual(combined_by_key["sugar_syrup"], 13.5)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_modifier_aware_fresh_fruit_tea_green_fixture(self):
        order_fixture = load_fixture("completed_fresh_fruit_tea_green.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "fresh_fruit_tea")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["green_tea"], 8.0)
        self.assertEqual(combined_by_key["sugar_syrup"], 54.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_fresh_mango_tea_fixture_adds_mango_syrup(self):
        order_fixture = load_fixture("completed_fresh_mango_tea_four_seasons.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "fresh_mango_tea")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["4s"], 8.0)
        self.assertEqual(combined_by_key["mango_syrup"], 35.0)
        self.assertEqual(combined_by_key["frozen_mango"], 30.0)
        self.assertEqual(combined_by_key["sugar_syrup"], 27.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_strawberry_matcha_latte_fixture_adds_frozen_strawberry(self):
        order_fixture = load_fixture("completed_strawberry_matcha_latte.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "strawberry_matcha_latte")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertEqual(combined_by_key["frozen_strawberry"], 30.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_additive_boba_modifier_fixture(self):
        order_fixture = load_fixture("completed_matcha_latte_boba.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "matcha_latte")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertEqual(combined_by_key["boba"], 100.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

    def test_additive_lychee_jelly_modifier_fixture(self):
        order_fixture = load_fixture("completed_matcha_latte_lychee_jelly.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "matcha_latte")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertEqual(combined_by_key["lychee_jelly"], 100.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

    def test_additive_hun_kue_modifier_fixture(self):
        order_fixture = load_fixture("completed_matcha_latte_hun_kue.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "matcha_latte")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertAlmostEqual(combined_by_key["hk_powder"], 8.571428571428571)
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 3.4285714285714284)
        self.assertAlmostEqual(combined_by_key["brown_sugar"], 3.4285714285714284)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

    def test_additive_tea_jelly_modifier_fixture(self):
        order_fixture = load_fixture("completed_matcha_latte_tea_jelly.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "matcha_latte")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertAlmostEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertAlmostEqual(combined_by_key["tgy"], 2.3255813953488373)
        self.assertAlmostEqual(combined_by_key["tj_powder"], 5.813953488372093)
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 3.488372093023256)
        self.assertAlmostEqual(combined_by_key["sugar_syrup"], 3.488372093023256)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

    def test_brown_sugar_cream_foam_modifier_fixture(self):
        order_fixture = load_fixture("completed_matcha_latte_brown_sugar_cream_foam.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "matcha_latte")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 185.71428571428572)
        self.assertAlmostEqual(combined_by_key["heavy_cream"], 8.928571428571429)
        self.assertAlmostEqual(
            combined_by_key["cream_foam_powder"], 8.928571428571429
        )
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 2.642857142857143)
        self.assertAlmostEqual(combined_by_key["brown_sugar"], 2.642857142857143)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)
        self.assertEqual(combined_by_key["cold_cup_lid"], 1.0)

    def test_pistachio_foam_modifier_fixture(self):
        order_fixture = load_fixture("completed_matcha_latte_pistachio_foam.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "matcha_latte")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 189.28571428571428)
        self.assertAlmostEqual(combined_by_key["heavy_cream"], 8.571428571428571)
        self.assertAlmostEqual(
            combined_by_key["cream_foam_powder"], 8.571428571428571
        )
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 5.357142857142857)
        self.assertAlmostEqual(combined_by_key["pistachio"], 8.928571428571429)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)
        self.assertEqual(combined_by_key["cold_cup_lid"], 1.0)

    def test_four_seasons_au_lait_fixture_adds_milk(self):
        order_fixture = load_fixture("completed_four_seasons_au_lait.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "four_seasons_au_lait")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertAlmostEqual(combined_by_key["4s"], 5.333333333333333)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_signature_black_milk_tea_fixture_adds_creamer(self):
        order_fixture = load_fixture("completed_signature_black_milk_tea.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(projected_line_items[0]["drink_key"], "signature_black_milk_tea")

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["black_tea"], 7.0)
        self.assertEqual(combined_by_key["non_dairy_creamer"], 37.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_combined_au_lait_and_milk_tea_fixture_rolls_up(self):
        order_fixture = load_fixture("completed_au_lait_and_milk_tea.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 2)

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertAlmostEqual(combined_by_key["4s"], 5.333333333333333)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertEqual(combined_by_key["black_tea"], 7.0)
        self.assertEqual(combined_by_key["non_dairy_creamer"], 37.0)
        self.assertEqual(combined_by_key["u600_cup"], 2.0)
        self.assertEqual(combined_by_key["small_straw"], 2.0)

    def test_modifier_aware_fresh_fruit_tea_missing_modifier_raises(self):
        order_fixture = load_fixture("completed_fresh_fruit_tea_missing_modifier.json")

        with self.assertRaisesRegex(
            ValueError,
            "No matching modifier override found for recipe 'fresh_fruit_tea'",
        ):
            project_fixture_order(order_fixture)

    def test_modifier_aware_fresh_fruit_tea_missing_sugar_raises(self):
        order_fixture = load_fixture("completed_fresh_fruit_tea_missing_sugar.json")

        with self.assertRaisesRegex(
            ValueError,
            "No matching sugar modifier found for recipe 'fresh_fruit_tea'",
        ):
            project_fixture_order(order_fixture)


if __name__ == "__main__":
    unittest.main()
