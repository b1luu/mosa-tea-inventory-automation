import unittest

from scripts.validate_recipe_map import validate


class ValidateRecipeMapTests(unittest.TestCase):
    def test_valid_recipe_map_passes(self):
        recipe_map = {
            "tea_bases": {
                "green": {
                    "ingredients": [{"inventory_key": "green_tea"}],
                }
            },
            "sold_variation_recipes": {
                "sold-1": {
                    "ingredients": [{"inventory_key": "milk"}],
                    "sugar_config": {"inventory_key": "sugar_syrup"},
                    "modifier_overrides": {
                        "mod-1": {
                            "ingredients": [{"inventory_key": "boba"}],
                        }
                    },
                }
            },
            "modifier_additions": {
                "mod-2": {
                    "ingredients": [{"inventory_key": "jelly"}],
                }
            },
            "default_sugar_config": {"inventory_key": "sugar_syrup"},
            "default_packaging_config": {
                "cup": {"inventory_key": "u600_cup"},
                "small_straw": {"inventory_key": "small_straw"},
            },
        }
        inventory_item_map = {
            "green_tea": {},
            "milk": {},
            "sugar_syrup": {},
            "boba": {},
            "jelly": {},
            "u600_cup": {},
            "small_straw": {},
        }

        self.assertEqual(validate(recipe_map, inventory_item_map), [])

    def test_missing_inventory_key_fails(self):
        recipe_map = {
            "sold_variation_recipes": {
                "72KIPS2KHWEK6RAT452MAB2P": {
                    "ingredients": [{"inventory_key": "milk_typo"}],
                }
            }
        }

        errors = validate(recipe_map, {"milk": {}})

        self.assertEqual(len(errors), 1)
        self.assertIn("milk_typo", errors[0])
        self.assertIn(
            "sold_variation_recipes['72KIPS2KHWEK6RAT452MAB2P'].ingredients[0].inventory_key",
            errors[0],
        )


if __name__ == "__main__":
    unittest.main()
