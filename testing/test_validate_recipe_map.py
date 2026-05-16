from decimal import Decimal
import unittest

from scripts.validate_recipe_map import find_orphan_inventory_keys, validate


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
                    "drink_key": "milk_tea",
                    "drink_name": "Milk Tea",
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
                    "drink_key": "broken_milk_tea",
                    "drink_name": "Broken Milk Tea",
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

    def test_drink_key_missing_on_non_redirect_fails(self):
        errors = validate(
            {
                "sold_variation_recipes": {
                    "sold-1": {
                        "drink_name": "Milk Tea",
                    }
                }
            },
            {},
        )

        self.assertIn(
            "sold_variation_recipes['sold-1'].drink_key: missing or empty on non-redirect recipe",
            errors,
        )

    def test_drink_name_missing_on_non_redirect_fails(self):
        errors = validate(
            {
                "sold_variation_recipes": {
                    "sold-1": {
                        "drink_key": "milk_tea",
                    }
                }
            },
            {},
        )

        self.assertIn(
            "sold_variation_recipes['sold-1'].drink_name: missing or empty on non-redirect recipe",
            errors,
        )

    def test_redirect_without_drink_key_passes(self):
        errors = validate(
            {
                "sold_variation_recipes": {
                    "sold-1": {"same_as_sold_variation_id": "sold-2"},
                    "sold-2": {
                        "drink_key": "milk_tea",
                        "drink_name": "Milk Tea",
                    },
                }
            },
            {},
        )

        self.assertEqual(errors, [])

    def test_same_as_sold_variation_id_missing_target_fails(self):
        errors = validate(
            {
                "sold_variation_recipes": {
                    "sold-1": {"same_as_sold_variation_id": "missing"},
                }
            },
            {},
        )

        self.assertIn(
            "sold_variation_recipes['sold-1'].same_as_sold_variation_id='missing': target not found in sold_variation_recipes",
            errors,
        )

    def test_same_as_sold_variation_id_cycle_fails(self):
        errors = validate(
            {
                "sold_variation_recipes": {
                    "A": {"same_as_sold_variation_id": "B"},
                    "B": {"same_as_sold_variation_id": "A"},
                }
            },
            {},
        )

        self.assertIn(
            "sold_variation_recipes['A'].same_as_sold_variation_id chain forms cycle: A -> B -> A",
            errors,
        )
        self.assertIn(
            "sold_variation_recipes['B'].same_as_sold_variation_id chain forms cycle: B -> A -> B",
            errors,
        )

    def test_same_as_sold_variation_id_long_chain_passes(self):
        errors = validate(
            {
                "sold_variation_recipes": {
                    "A": {"same_as_sold_variation_id": "B"},
                    "B": {"same_as_sold_variation_id": "C"},
                    "C": {
                        "drink_key": "milk_tea",
                        "drink_name": "Milk Tea",
                    },
                }
            },
            {},
        )

        self.assertEqual(errors, [])

    def test_ingredient_with_neither_key_fails(self):
        errors = validate(
            {
                "modifier_additions": {
                    "MOD": {
                        "ingredients": [{"amount": 1, "unit": "unit"}],
                    }
                }
            },
            {},
        )

        self.assertIn(
            "modifier_additions['MOD'].ingredients[0]: must have exactly one of inventory_key or tea_base_key (has neither)",
            errors,
        )

    def test_ingredient_with_both_keys_fails(self):
        errors = validate(
            {
                "modifier_additions": {
                    "MOD": {
                        "ingredients": [
                            {
                                "inventory_key": "boba",
                                "tea_base_key": "green",
                                "amount": 1,
                                "unit": "unit",
                            }
                        ],
                    }
                },
                "tea_bases": {"green": {"ingredients": []}},
            },
            {"boba": {}},
        )

        self.assertIn(
            "modifier_additions['MOD'].ingredients[0]: must have exactly one of inventory_key or tea_base_key (has both)",
            errors,
        )

    def test_ingredient_with_tea_base_key_passes(self):
        recipe_map = {
            "tea_bases": {
                "green": {
                    "ingredients": [{"inventory_key": "green_tea", "amount": 150, "unit": "ml"}],
                }
            },
            "sold_variation_recipes": {
                "sold-1": {
                    "drink_key": "green_tea",
                    "drink_name": "Green Tea",
                    "ingredients": [{"tea_base_key": "green"}],
                }
            },
        }

        self.assertEqual(validate(recipe_map, {"green_tea": {}}), [])

    def test_ingredient_with_unknown_tea_base_key_fails(self):
        errors = validate(
            {
                "sold_variation_recipes": {
                    "sold-1": {
                        "drink_key": "green_tea",
                        "drink_name": "Green Tea",
                        "ingredients": [{"tea_base_key": "unknown_base"}],
                    }
                }
            },
            {},
        )

        self.assertIn(
            "sold_variation_recipes['sold-1'].ingredients[0].tea_base_key='unknown_base': not found in tea_bases",
            errors,
        )

    def test_tea_base_key_ingredient_with_invalid_amount_fails(self):
        errors = validate(
            {
                "tea_bases": {"green": {"ingredients": []}},
                "sold_variation_recipes": {
                    "sold-1": {
                        "drink_key": "green_tea",
                        "drink_name": "Green Tea",
                        "ingredients": [{"tea_base_key": "green", "amount": -1, "unit": "ml"}],
                    }
                },
            },
            {},
        )

        self.assertIn(
            "sold_variation_recipes['sold-1'].ingredients[0].amount=-1: must be positive",
            errors,
        )

    def test_tea_base_key_ingredient_with_amount_exceeding_bound_fails(self):
        errors = validate(
            {
                "tea_bases": {"green": {"ingredients": []}},
                "sold_variation_recipes": {
                    "sold-1": {
                        "drink_key": "green_tea",
                        "drink_name": "Green Tea",
                        "ingredients": [{"tea_base_key": "green", "amount": 1500, "unit": "ml"}],
                    }
                },
            },
            {},
        )

        self.assertIn(
            "sold_variation_recipes['sold-1'].ingredients[0].amount=1500: exceeds upper bound 500 for unit 'ml'",
            errors,
        )

    def test_tea_base_key_ingredient_with_amount_no_unit_fails(self):
        errors = validate(
            {
                "tea_bases": {"green": {"ingredients": []}},
                "sold_variation_recipes": {
                    "sold-1": {
                        "drink_key": "green_tea",
                        "drink_name": "Green Tea",
                        "ingredients": [{"tea_base_key": "green", "amount": 300}],
                    }
                },
            },
            {},
        )

        self.assertIn(
            "sold_variation_recipes['sold-1'].ingredients[0].unit=None: missing",
            errors,
        )

    def test_orphan_inventory_key_emits_warning_but_not_error(self):
        recipe_map = {
            "tea_bases": {
                "green": {
                    "ingredients": [{"inventory_key": "green_tea", "amount": 150, "unit": "ml"}],
                }
            }
        }
        inventory_item_map = {
            "green_tea": {},
            "sample_cup": {},
        }

        self.assertEqual(validate(recipe_map, inventory_item_map), [])
        self.assertEqual(
            find_orphan_inventory_keys(recipe_map, inventory_item_map),
            ["inventory_item_map['sample_cup']: not referenced in recipe_map"],
        )


if __name__ == "__main__":
    unittest.main()
