from decimal import Decimal
import sys

from app.order_inventory_projection import load_inventory_item_map, load_recipe_map

ALLOWED_UNITS = ("ml", "g", "unit")
ALLOWED_UNITS_DISPLAY = "{'ml', 'g', 'unit'}"
NUMERIC_AMOUNT_TYPES = (int, float, Decimal)
AMOUNT_UPPER_BOUNDS = {
    "ml": 500,
    "g": 100,
    "unit": 5,
}


def _validate_inventory_key(errors, inventory_item_map, path, inventory_key):
    if inventory_key in inventory_item_map:
        return
    errors.append(f"{path}={inventory_key!r}: not found in inventory_item_map")


def _is_numeric_amount(value):
    return isinstance(value, NUMERIC_AMOUNT_TYPES) and not isinstance(value, bool)


def _validate_ingredient_amount_and_unit(errors, ingredient, path_prefix):
    amount_path = f"{path_prefix}.amount"
    unit_path = f"{path_prefix}.unit"

    if "amount" not in ingredient:
        errors.append(f"{amount_path}=None: missing")
        amount = None
    else:
        amount = ingredient.get("amount")
        if not _is_numeric_amount(amount):
            errors.append(f"{amount_path}={amount!r}: must be int, float, or Decimal")
        elif amount <= 0:
            errors.append(f"{amount_path}={amount!r}: must be positive")

    if "unit" not in ingredient:
        errors.append(f"{unit_path}=None: missing")
        unit = None
    else:
        unit = ingredient.get("unit")
        if unit not in ALLOWED_UNITS:
            errors.append(
                f"{unit_path}={unit!r}: not in allowed set {ALLOWED_UNITS_DISPLAY}"
            )

    if (
        _is_numeric_amount(amount)
        and amount > 0
        and unit in AMOUNT_UPPER_BOUNDS
        and amount > AMOUNT_UPPER_BOUNDS[unit]
    ):
        errors.append(
            f"{amount_path}={amount!r}: exceeds upper bound "
            f"{AMOUNT_UPPER_BOUNDS[unit]} for unit {unit!r}"
        )


def _validate_ingredients(errors, inventory_item_map, ingredients, path_prefix):
    for index, ingredient in enumerate(ingredients or []):
        ingredient_path = f"{path_prefix}[{index}]"
        inventory_key = ingredient.get("inventory_key")
        if inventory_key is None:
            continue
        _validate_inventory_key(
            errors,
            inventory_item_map,
            f"{ingredient_path}.inventory_key",
            inventory_key,
        )
        _validate_ingredient_amount_and_unit(errors, ingredient, ingredient_path)


def validate(recipe_map, inventory_item_map):
    errors = []

    for tea_base_key, tea_base in (recipe_map.get("tea_bases") or {}).items():
        _validate_ingredients(
            errors,
            inventory_item_map,
            tea_base.get("ingredients"),
            f"tea_bases[{tea_base_key!r}].ingredients",
        )

    for sold_variation_id, recipe in (recipe_map.get("sold_variation_recipes") or {}).items():
        recipe_path = f"sold_variation_recipes[{sold_variation_id!r}]"
        _validate_ingredients(
            errors,
            inventory_item_map,
            recipe.get("ingredients"),
            f"{recipe_path}.ingredients",
        )

        sugar_config = recipe.get("sugar_config")
        if sugar_config and sugar_config.get("inventory_key") is not None:
            _validate_inventory_key(
                errors,
                inventory_item_map,
                f"{recipe_path}.sugar_config.inventory_key",
                sugar_config["inventory_key"],
            )

        for modifier_id, override in (recipe.get("modifier_overrides") or {}).items():
            _validate_ingredients(
                errors,
                inventory_item_map,
                override.get("ingredients"),
                f"{recipe_path}.modifier_overrides[{modifier_id!r}].ingredients",
            )

    for modifier_id, addition in (recipe_map.get("modifier_additions") or {}).items():
        _validate_ingredients(
            errors,
            inventory_item_map,
            addition.get("ingredients"),
            f"modifier_additions[{modifier_id!r}].ingredients",
        )

    default_sugar_config = recipe_map.get("default_sugar_config") or {}
    if default_sugar_config.get("inventory_key") is not None:
        _validate_inventory_key(
            errors,
            inventory_item_map,
            "default_sugar_config.inventory_key",
            default_sugar_config["inventory_key"],
        )

    for packaging_key, packaging_entry in (recipe_map.get("default_packaging_config") or {}).items():
        if not isinstance(packaging_entry, dict):
            continue
        inventory_key = packaging_entry.get("inventory_key")
        if inventory_key is None:
            continue
        _validate_inventory_key(
            errors,
            inventory_item_map,
            f"default_packaging_config[{packaging_key!r}].inventory_key",
            inventory_key,
        )

    return errors


def main():
    errors = validate(
        load_recipe_map(),
        load_inventory_item_map(),
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("recipe_map validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
