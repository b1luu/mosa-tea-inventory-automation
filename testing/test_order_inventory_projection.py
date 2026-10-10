import json
import unittest
from decimal import Decimal
from pathlib import Path

from app.order_inventory_projection import (
    combine_projected_usage,
    project_line_item_usage,
)


FIXTURE_DIR = Path("testing/fixtures/orders")
FULL_SUGAR_MODIFIER_ID = "VEDNAO6LH5WQET6TQTJGSPOB"
FOUR_SEASONS_TEA_BASE_MODIFIER_ID = "76GJNMZXVLFOXRDRE23MR3FF"


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

    def test_hot_four_seasons_tea_alias_matches_cold_recipe(self):
        projected = project_line_item_usage(
            "3IUNOTOZ23VKQF3CT3FZGQJO",
            "1",
            ["IDFKCCIPYGFA67OPJMJ3SQVO"],
        )

        self.assertEqual(projected["drink_key"], "four_seasons_brewed_tea")
        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["4s"], 8.0)
        self.assertEqual(combined_by_key["hot_cup"], 1.0)
        self.assertEqual(combined_by_key["hot_lid"], 1.0)
        self.assertNotIn("u600_cup", combined_by_key)
        self.assertNotIn("small_straw", combined_by_key)
        self.assertNotIn("big_straw", combined_by_key)
        self.assertNotIn("cold_cup_lid", combined_by_key)

    def test_hot_matcha_latte_alias_matches_cold_recipe(self):
        projected = project_line_item_usage(
            "J23B26YNDV2WAAJIKDXKD3YR",
            "1",
            ["IDFKCCIPYGFA67OPJMJ3SQVO"],
        )

        self.assertEqual(projected["drink_key"], "matcha_latte")
        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertEqual(combined_by_key["hot_cup"], 1.0)
        self.assertEqual(combined_by_key["hot_lid"], 1.0)
        self.assertNotIn("u600_cup", combined_by_key)
        self.assertNotIn("small_straw", combined_by_key)
        self.assertNotIn("big_straw", combined_by_key)
        self.assertNotIn("cold_cup_lid", combined_by_key)

    def test_hot_matcha_latte_allows_boba_without_straw(self):
        projected = project_line_item_usage(
            "J23B26YNDV2WAAJIKDXKD3YR",
            "1",
            ["IDFKCCIPYGFA67OPJMJ3SQVO", "UIFT45SSDNEZBUDPKFGF6VES"],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertEqual(combined_by_key["boba"], 100.0)
        self.assertEqual(combined_by_key["hot_cup"], 1.0)
        self.assertEqual(combined_by_key["hot_lid"], 1.0)
        self.assertNotIn("small_straw", combined_by_key)
        self.assertNotIn("big_straw", combined_by_key)
        self.assertNotIn("cold_cup_lid", combined_by_key)

    def test_hot_matcha_latte_rejects_tea_jelly(self):
        with self.assertRaisesRegex(
            ValueError,
            "not supported for hot drink",
        ):
            project_line_item_usage(
                "J23B26YNDV2WAAJIKDXKD3YR",
                "1",
                ["IDFKCCIPYGFA67OPJMJ3SQVO", "MEAKOBKUZMU6PVM3OVPDYMJ2"],
            )

    def test_matcha_latte_matcha_jelly_modifier_fixture(self):
        projected = project_line_item_usage(
            "DX2LRA7T4EFSSFH6POETDJHY",
            "1",
            ["IDFKCCIPYGFA67OPJMJ3SQVO", "AB2HPG7C7F2V3DXPPXCEBNH4"],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["matcha"], 8.75)
        self.assertEqual(combined_by_key["milk"], 150.0)
        self.assertAlmostEqual(
            combined_by_key["matcha_jelly_matcha"], 1.6260162601626016
        )
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 12.195121951219512)
        self.assertAlmostEqual(combined_by_key["tj_powder"], 4.878048780487805)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

    def test_genmai_matcha_with_matcha_jelly_fixture(self):
        order_fixture = load_fixture("completed_genmai_matcha_with_matcha_jelly.json")
        projected_line_items, combined_usage = project_fixture_order(order_fixture)

        self.assertEqual(len(projected_line_items), 1)
        self.assertEqual(
            projected_line_items[0]["drink_key"], "genmai_matcha_with_matcha_jelly"
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in combined_usage
        }
        self.assertEqual(combined_by_key["matcha"], 6.5625)
        self.assertEqual(combined_by_key["genmai"], 4.0)
        self.assertAlmostEqual(
            combined_by_key["matcha_jelly_matcha"], 1.6260162601626016
        )
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 12.195121951219512)
        self.assertAlmostEqual(combined_by_key["tj_powder"], 4.878048780487805)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["big_straw"], 1.0)

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

    def test_projected_usage_amounts_remain_decimals(self):
        projected = project_line_item_usage(
            "72KIPS2KHWEK6RAT452MAB2P",
            "1",
            [FULL_SUGAR_MODIFIER_ID],
        )

        usage = projected["usage"][0]
        self.assertIsInstance(usage["recipe_amount"], Decimal)
        self.assertIsInstance(usage["per_drink_inventory_amount"], Decimal)
        self.assertIsInstance(usage["sold_quantity"], Decimal)
        self.assertIsInstance(usage["total_amount"], Decimal)

    def test_combined_usage_amounts_remain_decimals(self):
        projected = project_line_item_usage(
            "72KIPS2KHWEK6RAT452MAB2P",
            "1",
            [FULL_SUGAR_MODIFIER_ID],
        )

        combined_usage = combine_projected_usage([projected])
        self.assertIsInstance(combined_usage[0]["total_amount"], Decimal)

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
        self.assertEqual(combined_by_key["osmanthus_honey"], 37.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_tgy_milk_tea_with_osmanthus_honey_uses_37_grams(self):
        projected = project_line_item_usage(
            "5QYGSH5A7D3EOYGTBZMVEC7D",
            "1",
            [FULL_SUGAR_MODIFIER_ID],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["osmanthus_honey"], 37.0)

    def test_tgy_au_lait_with_osmanthus_honey_uses_37_grams(self):
        projected = project_line_item_usage(
            "YBWRTRH3ZE2OHQ5PL3V662WE",
            "1",
            [FULL_SUGAR_MODIFIER_ID],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["osmanthus_honey"], 37.0)

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
        self.assertEqual(combined_by_key["mango_syrup"], 37.0)
        self.assertEqual(combined_by_key["frozen_mango"], 30.0)
        self.assertEqual(combined_by_key["sugar_syrup"], 27.0)
        self.assertEqual(combined_by_key["u600_cup"], 1.0)
        self.assertEqual(combined_by_key["small_straw"], 1.0)

    def test_fresh_orange_tea_adds_orange_syrup(self):
        projected = project_line_item_usage(
            "KESNSNPZO3QYTJHW4STNDJNR",
            "1",
            [FULL_SUGAR_MODIFIER_ID, FOUR_SEASONS_TEA_BASE_MODIFIER_ID],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["orange_syrup"], 37.0)

    def test_fresh_lemon_tea_adds_lemon_syrup(self):
        projected = project_line_item_usage(
            "GL4SND76TJYPY6RBUU32N4HF",
            "1",
            [FULL_SUGAR_MODIFIER_ID, FOUR_SEASONS_TEA_BASE_MODIFIER_ID],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["lemon_syrup"], 37.0)

    def test_fresh_strawberry_tea_adds_strawberry_syrup(self):
        projected = project_line_item_usage(
            "QFNOAWWK3VZXJTZJAU4JRCFO",
            "1",
            [FULL_SUGAR_MODIFIER_ID, FOUR_SEASONS_TEA_BASE_MODIFIER_ID],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["strawberry_syrup"], 37.0)

    def test_fresh_grapefruit_tea_adds_grapefruit_syrup(self):
        projected = project_line_item_usage(
            "GWLUEE5JMJLJITJRR42G6GHV",
            "1",
            [FULL_SUGAR_MODIFIER_ID, FOUR_SEASONS_TEA_BASE_MODIFIER_ID],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["grapefruit_syrup"], 37.0)

    def test_fresh_apple_tea_adds_apple_syrup(self):
        projected = project_line_item_usage(
            "EN2VSTOAJGNMPKU5LMXF3MR6",
            "1",
            [FULL_SUGAR_MODIFIER_ID, FOUR_SEASONS_TEA_BASE_MODIFIER_ID],
        )

        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertEqual(combined_by_key["apple_syrup"], 37.0)

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

    def test_ssr_oolong_tea_deducts_brewed_leaves_only(self):
        # Find SSR Oolong Tea by drink_key (synthetic canonical id varies per
        # generation). 1 drink = 300ml brewed SSR Oolong → 100/4700 * 300 = 6.383g
        from app.order_inventory_projection import load_recipe_map
        recipes = load_recipe_map()
        ssr_tea_id = next(
            cid for cid, r in recipes["sold_variation_recipes"].items()
            if r.get("drink_key") == "ssr_oolong_brewed_tea"
        )
        no_sugar = "IDFKCCIPYGFA67OPJMJ3SQVO"
        projected = project_line_item_usage(ssr_tea_id, "1", [no_sugar])
        combined = {u["inventory_key"]: u["total_amount"] for u in projected["usage"]}
        self.assertAlmostEqual(combined["ssr_oolong"], 100 * 300 / 4700)
        self.assertEqual(combined["u600_cup"], 1.0)
        self.assertEqual(combined["small_straw"], 1.0)
        self.assertNotIn("cold_cup_lid", combined)

    def test_ssr_oolong_au_lait_deducts_milk(self):
        from app.order_inventory_projection import load_recipe_map
        recipes = load_recipe_map()
        ssr_au_lait_id = next(
            cid for cid, r in recipes["sold_variation_recipes"].items()
            if r.get("drink_key") == "ssr_oolong_au_lait"
        )
        no_sugar = "IDFKCCIPYGFA67OPJMJ3SQVO"
        projected = project_line_item_usage(ssr_au_lait_id, "1", [no_sugar])
        combined = {u["inventory_key"]: u["total_amount"] for u in projected["usage"]}
        self.assertAlmostEqual(combined["ssr_oolong"], 100 * 200 / 4700)
        self.assertEqual(combined["milk"], 150.0)

    def test_ssr_special_deducts_built_in_silky_custard(self):
        # SSR Special is the SSR milk tea + Silky Custard built in.
        # Expect ssr_oolong + non_dairy_creamer + heavy_cream + creme_brulee_powder.
        from app.order_inventory_projection import load_recipe_map
        recipes = load_recipe_map()
        ssr_special_id = next(
            cid for cid, r in recipes["sold_variation_recipes"].items()
            if r.get("drink_key") == "ssr_special"
        )
        no_sugar = "IDFKCCIPYGFA67OPJMJ3SQVO"
        projected = project_line_item_usage(ssr_special_id, "1", [no_sugar])
        combined = {u["inventory_key"]: u["total_amount"] for u in projected["usage"]}
        self.assertAlmostEqual(combined["ssr_oolong"], 100 * 300 / 4700)
        self.assertEqual(combined["non_dairy_creamer"], 37.0)
        # Built-in Silky Custard (21-cup batch derivation)
        self.assertAlmostEqual(combined["heavy_cream"], 700 / 21)
        self.assertAlmostEqual(combined["creme_brulee_powder"], 280 / 21)

    def test_silky_custard_modifier_on_other_drink(self):
        # Adding the Silky Custard modifier to any drink deducts the same
        # heavy_cream + creme_brulee_powder amounts as the built-in inlining.
        from app.order_inventory_projection import load_recipe_map
        recipes = load_recipe_map()
        silky_id = next(
            mid for mid, payload in recipes["modifier_additions"].items()
            if any(i["inventory_key"] == "creme_brulee_powder" for i in payload["ingredients"])
        )
        # Apply to a known drink (Matcha Latte). Need a sugar modifier too.
        matcha_latte_id = "DX2LRA7T4EFSSFH6POETDJHY"
        no_sugar = "IDFKCCIPYGFA67OPJMJ3SQVO"
        projected = project_line_item_usage(matcha_latte_id, "1", [no_sugar, silky_id])
        combined = {u["inventory_key"]: u["total_amount"] for u in projected["usage"]}
        self.assertAlmostEqual(combined["heavy_cream"], 700 / 21)
        self.assertAlmostEqual(combined["creme_brulee_powder"], 280 / 21)

    def _project_brown_sugar_drink(self, drink_key, modifier_ids):
        # Brown Sugar series: the tea comes from the Tea Base modifier (300ml of
        # the chosen tea, 200ml for the Au Lait), brown sugar from the Brown
        # Sugar Sweetness modifier (one 37g shot at Regular Sweet).
        from app.order_inventory_projection import load_recipe_map
        recipes = load_recipe_map()
        sold_variation_id = next(
            cid for cid, r in recipes["sold_variation_recipes"].items()
            if r.get("drink_key") == drink_key
        )
        projected = project_line_item_usage(sold_variation_id, "1", modifier_ids)
        return {u["inventory_key"]: float(u["total_amount"]) for u in projected["usage"]}

    def test_brown_sugar_milk_tea_deducts_selected_tea_creamer_and_one_shot(self):
        tgy_tea = "MOSAEXT_MOD_BS_TEA_TGY_0A0DE0B6"
        regular_sweet = "MOSAEXT_MOD_BS_SWEET_REGULAR_E4870952"
        combined = self._project_brown_sugar_drink(
            "brown_sugar_milk_tea", [tgy_tea, regular_sweet]
        )
        self.assertAlmostEqual(combined["tgy"], 160 * 300 / 6000)
        self.assertAlmostEqual(combined["non_dairy_creamer"], 37.0)
        self.assertAlmostEqual(combined["brown_sugar"], 37.0)
        self.assertNotIn("sugar_syrup", combined)
        self.assertNotIn("milk", combined)
        self.assertEqual(combined["u600_cup"], 1.0)
        self.assertEqual(combined["small_straw"], 1.0)

    def test_brown_sugar_sweetness_scales_the_shot(self):
        black_tea = "MOSAEXT_MOD_BS_TEA_BLACK_6448B6FC"
        expected_by_sweetness = {
            "MOSAEXT_MOD_BS_SWEET_LESS_40ECA99F": 18.5,
            "MOSAEXT_MOD_BS_SWEET_REGULAR_E4870952": 37.0,
            "MOSAEXT_MOD_BS_SWEET_EXTRA_57FEA76A": 74.0,
        }
        for sweetness_modifier_id, expected_grams in expected_by_sweetness.items():
            combined = self._project_brown_sugar_drink(
                "brown_sugar_milk_tea", [black_tea, sweetness_modifier_id]
            )
            self.assertAlmostEqual(combined["brown_sugar"], expected_grams)
            self.assertAlmostEqual(combined["black_tea"], 140 * 300 / 6000)

    def test_brown_sugar_tea_au_lait_deducts_milk_and_blended_tea_base(self):
        genmai_green_tea = "MOSAEXT_MOD_BS_TEA_GENMAI_GREEN_9912088D"
        less_sweet = "MOSAEXT_MOD_BS_SWEET_LESS_40ECA99F"
        combined = self._project_brown_sugar_drink(
            "brown_sugar_tea_au_lait", [genmai_green_tea, less_sweet]
        )
        # 200ml of tea like the other Au Laits, split evenly across the blend.
        self.assertAlmostEqual(combined["milk"], 150.0)
        self.assertAlmostEqual(combined["genmai"], 120 * 100 / 6000)
        self.assertAlmostEqual(combined["green_tea"], 160 * 100 / 6000)
        self.assertAlmostEqual(combined["brown_sugar"], 18.5)
        self.assertNotIn("non_dairy_creamer", combined)

    def test_brown_sugar_tea_au_lait_uses_200ml_of_single_origin_tea(self):
        tgy_tea = "MOSAEXT_MOD_BS_TEA_TGY_0A0DE0B6"
        regular_sweet = "MOSAEXT_MOD_BS_SWEET_REGULAR_E4870952"
        combined = self._project_brown_sugar_drink(
            "brown_sugar_tea_au_lait", [tgy_tea, regular_sweet]
        )
        self.assertAlmostEqual(combined["tgy"], 160 * 200 / 6000)
        self.assertAlmostEqual(combined["milk"], 150.0)
        self.assertAlmostEqual(combined["brown_sugar"], 37.0)

    def test_brown_sugar_frost_uses_two_shots_regardless_of_sweetness(self):
        buckwheat_four_seasons_tea = "MOSAEXT_MOD_BS_TEA_BUCKWHEAT_4S_344A9D0F"
        for sweetness_modifier_id in (
            "MOSAEXT_MOD_BS_SWEET_LESS_40ECA99F",
            "MOSAEXT_MOD_BS_SWEET_EXTRA_57FEA76A",
        ):
            combined = self._project_brown_sugar_drink(
                "brown_sugar_frost", [buckwheat_four_seasons_tea, sweetness_modifier_id]
            )
            self.assertAlmostEqual(combined["brown_sugar"], 74.0)
            self.assertAlmostEqual(combined["non_dairy_creamer"], 37.0)
            self.assertAlmostEqual(combined["4s"], 160 * 225 / 6000)
            self.assertAlmostEqual(combined["buckwheat"], 120 * 37.5 / 6000)
            self.assertAlmostEqual(combined["barley"], 240 * 37.5 / 6000)

    def test_hot_brown_sugar_milk_tea_matches_cold_recipe_with_hot_packaging(self):
        from app.order_inventory_projection import load_recipe_map
        recipes = load_recipe_map()
        cold_id = next(
            cid for cid, r in recipes["sold_variation_recipes"].items()
            if r.get("drink_key") == "brown_sugar_milk_tea"
        )
        hot_id = next(
            cid for cid, r in recipes["sold_variation_recipes"].items()
            if r.get("same_as_sold_variation_id") == cold_id
        )
        buckwheat_barley_tea = "MOSAEXT_MOD_BS_TEA_BUCKWHEAT_BARLEY_E33CF4DD"
        regular_sweet = "MOSAEXT_MOD_BS_SWEET_REGULAR_E4870952"
        projected = project_line_item_usage(
            hot_id, "1", [buckwheat_barley_tea, regular_sweet]
        )
        combined = {u["inventory_key"]: float(u["total_amount"]) for u in projected["usage"]}
        self.assertEqual(projected["drink_key"], "brown_sugar_milk_tea")
        self.assertAlmostEqual(combined["buckwheat"], 120 * 150 / 6000)
        self.assertAlmostEqual(combined["barley"], 240 * 150 / 6000)
        self.assertAlmostEqual(combined["non_dairy_creamer"], 37.0)
        self.assertAlmostEqual(combined["brown_sugar"], 37.0)
        self.assertEqual(combined["hot_cup"], 1.0)
        self.assertEqual(combined["hot_lid"], 1.0)
        self.assertNotIn("u600_cup", combined)
        self.assertNotIn("small_straw", combined)

    def test_brown_sugar_milk_tea_without_tea_base_modifier_deducts_no_tea(self):
        # The live Tea Base list is optional, so a few real tickets carry no tea
        # choice. The drink still deducts creamer and brown sugar.
        regular_sweet = "MOSAEXT_MOD_BS_SWEET_REGULAR_E4870952"
        combined = self._project_brown_sugar_drink("brown_sugar_milk_tea", [regular_sweet])
        self.assertAlmostEqual(combined["non_dairy_creamer"], 37.0)
        self.assertAlmostEqual(combined["brown_sugar"], 37.0)
        for tea_key in ("tgy", "black_tea", "4s", "genmai", "green_tea", "buckwheat", "barley"):
            self.assertNotIn(tea_key, combined)

    def test_brown_sugar_mist_built_in_cream_foam_no_modifier(self):
        # Brown Sugar Mist has Brown Sugar Cream Foam built-in — no cream
        # foam modifier is selected on the order, but the projection must
        # still deduct the cream foam ingredients AND a cold_cup_lid.
        # (A sugar modifier is always required by the recipe, so include
        # 'No Sugar' to isolate the cream foam behavior.)
        no_sugar_modifier_id = "IDFKCCIPYGFA67OPJMJ3SQVO"
        projected = project_line_item_usage(
            "NRVPY6OAHI42VTZEMYHTDQ4N",
            "1",
            [no_sugar_modifier_id],
        )

        self.assertEqual(projected["drink_key"], "brown_sugar_mist")
        combined_by_key = {
            usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]
        }
        self.assertAlmostEqual(combined_by_key["tgy"], 8.0)
        self.assertAlmostEqual(combined_by_key["milk"], 35.714285714285715)
        self.assertAlmostEqual(combined_by_key["heavy_cream"], 8.928571428571429)
        self.assertAlmostEqual(combined_by_key["cream_foam_powder"], 8.928571428571429)
        self.assertAlmostEqual(combined_by_key["powdered_sugar"], 2.642857142857143)
        self.assertAlmostEqual(combined_by_key["brown_sugar"], 2.642857142857143)
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
