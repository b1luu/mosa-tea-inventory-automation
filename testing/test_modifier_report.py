import unittest

from scripts.modifier_report import _modifier_roles, build_report


RECIPE_MAP = {
    "sugar_modifier_multipliers": {
        "SUGAR25": 0.25,
    },
    "modifier_additions": {
        "BOBA": {"ingredients": [{"inventory_key": "boba", "amount": 100, "unit": "g"}]},
    },
    "default_packaging_config": {
        "topping_modifier_ids": ["BOBA"],
        "hot_allowed_topping_modifier_ids": [],
        "cream_foam_modifier_ids": ["FOAM"],
    },
    "sold_variation_recipes": {
        "drink-1": {"modifier_overrides": {"TEABASE": {"ingredients": []}}},
    },
}


class ModifierRolesTests(unittest.TestCase):
    def test_classifies_sugar_with_multiplier(self):
        self.assertEqual(_modifier_roles("SUGAR25", RECIPE_MAP), ["sugar x0.25"])

    def test_classifies_ingredient_and_topping(self):
        self.assertEqual(_modifier_roles("BOBA", RECIPE_MAP), ["ingredient", "topping"])

    def test_classifies_foam(self):
        self.assertEqual(_modifier_roles("FOAM", RECIPE_MAP), ["foam"])

    def test_classifies_recipe_override(self):
        self.assertEqual(_modifier_roles("TEABASE", RECIPE_MAP), ["recipe-override"])

    def test_unmapped_modifier_returns_no_roles(self):
        self.assertEqual(_modifier_roles("STICKER", RECIPE_MAP), [])


class BuildReportTests(unittest.TestCase):
    def setUp(self):
        self.modifier_lists = {
            "LIST_A": {
                "name": "Sugar Level",
                "selection_type": "SINGLE",
                "modifier_count": 1,
                "item_count": 5,
            },
            "LIST_B": {
                "name": "Sugar Level (Minimum Sugar Required)",
                "selection_type": "SINGLE",
                "modifier_count": 1,
                "item_count": 3,
            },
            "LIST_ORPHAN": {
                "name": "Sticker Selection",
                "selection_type": "SINGLE",
                "modifier_count": 1,
                "item_count": 0,
            },
        }
        self.modifiers = [
            {"id": "SUGAR25", "name": "25% Sugar", "modifier_list_id": "LIST_A"},
            {"id": "SUGAR25_DUP", "name": "25% Sugar", "modifier_list_id": "LIST_B"},
            {"id": "STICKER", "name": "Mosa Logo", "modifier_list_id": "LIST_ORPHAN"},
        ]
        # SUGAR25_DUP needs a multiplier too, so both instances classify as sugar
        self.recipe_map = {
            **RECIPE_MAP,
            "sugar_modifier_multipliers": {"SUGAR25": 0.25, "SUGAR25_DUP": 0.25},
        }

    def test_flags_duplicated_name(self):
        _, name_rows, _ = build_report(self.modifier_lists, self.modifiers, self.recipe_map)
        sugar_row = next(r for r in name_rows if r["name"] == "25% Sugar")
        self.assertTrue(sugar_row["duplicated"])
        self.assertEqual(sugar_row["instance_count"], 2)
        self.assertTrue(sugar_row["mapped"])

    def test_flags_unmapped_name(self):
        _, name_rows, _ = build_report(self.modifier_lists, self.modifiers, self.recipe_map)
        sticker_row = next(r for r in name_rows if r["name"] == "Mosa Logo")
        self.assertFalse(sticker_row["mapped"])
        self.assertFalse(sticker_row["duplicated"])

    def test_flags_orphaned_list(self):
        list_rows, _, _ = build_report(self.modifier_lists, self.modifiers, self.recipe_map)
        orphan = next(r for r in list_rows if r["id"] == "LIST_ORPHAN")
        active = next(r for r in list_rows if r["id"] == "LIST_A")
        self.assertTrue(orphan["orphaned"])
        self.assertFalse(active["orphaned"])

    def test_summary_counts(self):
        _, _, summary = build_report(self.modifier_lists, self.modifiers, self.recipe_map)
        self.assertEqual(summary["modifier_list_count"], 3)
        self.assertEqual(summary["orphaned_list_count"], 1)
        self.assertEqual(summary["distinct_modifier_names"], 2)
        self.assertEqual(summary["total_modifier_objects"], 3)
        self.assertEqual(summary["duplicated_name_count"], 1)
        self.assertEqual(summary["unmapped_name_count"], 1)


if __name__ == "__main__":
    unittest.main()
