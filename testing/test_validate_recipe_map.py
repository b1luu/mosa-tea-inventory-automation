from decimal import Decimal
import unittest

from scripts.validate_recipe_map import validate


class ValidateRecipeMapTests(unittest.TestCase):
    def test_valid_recipe_map_passes(self):
        recipe_map = {
            "tea_bases": {
                "green": {
                    "ingredients": [{"inventory_key": "green_tea", "amount": 150, "unit": "ml"}],
                }
            },
            "sold_variation_recipes": {
                "sold-1": {
                    "ingredients": [{"inventory_key": "milk", "amount": 10, "unit": "g"}],
                    "sugar_config": {"inventory_key": "sugar_syrup"},
                    "modifier_overrides": {
                        "mod-1": {
                            "ingredients": [{"inventory_key": "boba", "amount": 1, "unit": "unit"}],
                        }
                    },
                }
            },
            "modifier_additions": {
                "mod-2": {
                    "ingredients": [{"inventory_key": "jelly", "amount": 1, "unit": "unit"}],
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
                    "ingredients": [{"inventory_key": "milk_typo", "amount": 150, "unit": "ml"}],
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

    def test_negative_amount_fails(self):
        errors = validate(
            {
                "tea_bases": {
                    "green": {
                        "ingredients": [{"inventory_key": "green_tea", "amount": -1.0, "unit": "ml"}],
                    }
                }
            },
            {"green_tea": {}},
        )

        self.assertIn("tea_bases['green'].ingredients[0].amount=-1.0: must be positive", errors)

    def test_zero_amount_fails(self):
        errors = validate(
            {
                "tea_bases": {
                    "green": {
                        "ingredients": [{"inventory_key": "green_tea", "amount": 0, "unit": "ml"}],
                    }
                }
            },
            {"green_tea": {}},
        )

        self.assertIn("tea_bases['green'].ingredients[0].amount=0: must be positive", errors)

    def test_unknown_unit_fails(self):
        errors = validate(
            {
                "tea_bases": {
                    "green": {
                        "ingredients": [{"inventory_key": "green_tea", "amount": 1, "unit": "liters"}],
                    }
                }
            },
            {"green_tea": {}},
        )

        self.assertIn(
            "tea_bases['green'].ingredients[0].unit='liters': not in allowed set {'ml', 'g', 'unit'}",
            errors,
        )

    def test_amount_exceeds_ml_bound_fails(self):
        errors = validate(
            {
                "tea_bases": {
                    "green": {
                        "ingredients": [{"inventory_key": "green_tea", "amount": 1500, "unit": "ml"}],
                    }
                }
            },
            {"green_tea": {}},
        )

        self.assertIn(
            "tea_bases['green'].ingredients[0].amount=1500: exceeds upper bound 500 for unit 'ml'",
            errors,
        )

    def test_amount_exceeds_g_bound_fails(self):
        errors = validate(
            {
                "tea_bases": {
                    "green": {
                        "ingredients": [{"inventory_key": "green_tea", "amount": 200, "unit": "g"}],
                    }
                }
            },
            {"green_tea": {}},
        )

        self.assertIn(
            "tea_bases['green'].ingredients[0].amount=200: exceeds upper bound 100 for unit 'g'",
            errors,
        )

    def test_amount_exceeds_unit_bound_fails(self):
        errors = validate(
            {
                "tea_bases": {
                    "green": {
                        "ingredients": [{"inventory_key": "green_tea", "amount": 10, "unit": "unit"}],
                    }
                }
            },
            {"green_tea": {}},
        )

        self.assertIn(
            "tea_bases['green'].ingredients[0].amount=10: exceeds upper bound 5 for unit 'unit'",
            errors,
        )

    def test_valid_amounts_and_units_pass(self):
        recipe_map = {
            "tea_bases": {
                "green": {
                    "ingredients": [
                        {"inventory_key": "tea", "amount": 150, "unit": "ml"},
                        {"inventory_key": "powder", "amount": 10, "unit": "g"},
                        {"inventory_key": "cup", "amount": 1, "unit": "unit"},
                    ],
                }
            }
        }
        inventory_item_map = {
            "tea": {},
            "powder": {},
            "cup": {},
        }

        self.assertEqual(validate(recipe_map, inventory_item_map), [])

    def test_decimal_amount_passes(self):
        errors = validate(
            {
                "tea_bases": {
                    "green": {
                        "ingredients": [
                            {
                                "inventory_key": "green_tea",
                                "amount": Decimal("37.5"),
                                "unit": "ml",
                            }
                        ],
                    }
                }
            },
            {"green_tea": {}},
        )

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
