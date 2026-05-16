from decimal import Decimal
import sys

from app.order_inventory_projection import load_inventory_item_map, load_recipe_map

ALLOWED_UNITS = ("ml", "g", "unit")
ALLOWED_UNITS_DISPLAY = "{" + ", ".join(repr(unit) for unit in ALLOWED_UNITS) + "}"
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


def _validate_tea_base_key(errors, tea_bases, path, tea_base_key):
    if tea_base_key in tea_bases:
        return
    errors.append(f"{path}={tea_base_key!r}: not found in tea_bases")


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


def _iter_ingredient_sites(recipe_map):
    for tea_base_key, tea_base in (recipe_map.get("tea_bases") or {}).items():
        yield f"tea_bases[{tea_base_key!r}].ingredients", tea_base.get("ingredients")

    for sold_variation_id, recipe in (recipe_map.get("sold_variation_recipes") or {}).items():
        recipe_path = f"sold_variation_recipes[{sold_variation_id!r}]"
        yield f"{recipe_path}.ingredients", recipe.get("ingredients")

        for modifier_id, override in (recipe.get("modifier_overrides") or {}).items():
            yield (
                f"{recipe_path}.modifier_overrides[{modifier_id!r}].ingredients",
                override.get("ingredients"),
            )

    for modifier_id, addition in (recipe_map.get("modifier_additions") or {}).items():
        yield f"modifier_additions[{modifier_id!r}].ingredients", addition.get("ingredients")


def _validate_recipe_identity(errors, sold_variation_recipes):
    for sold_variation_id, recipe in sold_variation_recipes.items():
        if recipe.get("same_as_sold_variation_id") is not None:
            continue

        recipe_path = f"sold_variation_recipes[{sold_variation_id!r}]"
        drink_key = recipe.get("drink_key")
        drink_name = recipe.get("drink_name")

        if not isinstance(drink_key, str) or not drink_key.strip():
            errors.append(f"{recipe_path}.drink_key: missing or empty on non-redirect recipe")
        if not isinstance(drink_name, str) or not drink_name.strip():
            errors.append(f"{recipe_path}.drink_name: missing or empty on non-redirect recipe")


def _validate_same_as_chains(errors, sold_variation_recipes):
    for sold_variation_id, recipe in sold_variation_recipes.items():
        target = recipe.get("same_as_sold_variation_id")
        if target is None:
            continue

        path = f"sold_variation_recipes[{sold_variation_id!r}].same_as_sold_variation_id"
        chain = [sold_variation_id]
        current_target = target

        while current_target is not None:
            if current_target not in sold_variation_recipes:
                errors.append(f"{path}={current_target!r}: target not found in sold_variation_recipes")
                break
            if current_target in chain:
                errors.append(
                    f"{path} chain forms cycle: {' -> '.join(chain + [current_target])}"
                )
                break

            chain.append(current_target)
            current_target = sold_variation_recipes[current_target].get(
                "same_as_sold_variation_id"
            )


def _validate_ingredients(errors, inventory_item_map, tea_bases, ingredients, path_prefix):
    for index, ingredient in enumerate(ingredients or []):
        ingredient_path = f"{path_prefix}[{index}]"
        inventory_key = ingredient.get("inventory_key")
        tea_base_key = ingredient.get("tea_base_key")
        has_inventory_key = inventory_key is not None
        has_tea_base_key = tea_base_key is not None

        if has_inventory_key == has_tea_base_key:
            state = "both" if has_inventory_key else "neither"
            errors.append(
                f"{ingredient_path}: must have exactly one of inventory_key or "
                f"tea_base_key (has {state})"
            )
            continue

        if has_inventory_key:
            _validate_inventory_key(
                errors,
                inventory_item_map,
                f"{ingredient_path}.inventory_key",
                inventory_key,
            )
            _validate_ingredient_amount_and_unit(errors, ingredient, ingredient_path)
            continue

        _validate_tea_base_key(
            errors,
            tea_bases,
            f"{ingredient_path}.tea_base_key",
            tea_base_key,
        )
        if "amount" in ingredient or "unit" in ingredient:
            _validate_ingredient_amount_and_unit(errors, ingredient, ingredient_path)


def find_orphan_inventory_keys(recipe_map, inventory_item_map):
    referenced_inventory_keys = set()

    for _, ingredients in _iter_ingredient_sites(recipe_map):
        for ingredient in ingredients or []:
            inventory_key = ingredient.get("inventory_key")
            if inventory_key is not None:
                referenced_inventory_keys.add(inventory_key)

    for recipe in (recipe_map.get("sold_variation_recipes") or {}).values():
        sugar_config = recipe.get("sugar_config")
        if sugar_config and sugar_config.get("inventory_key") is not None:
            referenced_inventory_keys.add(sugar_config["inventory_key"])

    default_sugar_config = recipe_map.get("default_sugar_config") or {}
    if default_sugar_config.get("inventory_key") is not None:
        referenced_inventory_keys.add(default_sugar_config["inventory_key"])

    for packaging_entry in (recipe_map.get("default_packaging_config") or {}).values():
        if not isinstance(packaging_entry, dict):
            continue
        inventory_key = packaging_entry.get("inventory_key")
        if inventory_key is not None:
            referenced_inventory_keys.add(inventory_key)

    return [
        f"inventory_item_map[{inventory_key!r}]: not referenced in recipe_map"
        for inventory_key in sorted(set(inventory_item_map) - referenced_inventory_keys)
    ]


def validate(recipe_map, inventory_item_map):
    errors = []
    tea_bases = recipe_map.get("tea_bases") or {}
    sold_variation_recipes = recipe_map.get("sold_variation_recipes") or {}

    _validate_recipe_identity(errors, sold_variation_recipes)
    _validate_same_as_chains(errors, sold_variation_recipes)

    for path_prefix, ingredients in _iter_ingredient_sites(recipe_map):
        _validate_ingredients(
            errors,
            inventory_item_map,
            tea_bases,
            ingredients,
            path_prefix,
        )

    for sold_variation_id, recipe in sold_variation_recipes.items():
        recipe_path = f"sold_variation_recipes[{sold_variation_id!r}]"
        sugar_config = recipe.get("sugar_config")
        if sugar_config and sugar_config.get("inventory_key") is not None:
            _validate_inventory_key(
                errors,
                inventory_item_map,
                f"{recipe_path}.sugar_config.inventory_key",
                sugar_config["inventory_key"],
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
    recipe_map = load_recipe_map()
    inventory_item_map = load_inventory_item_map()
    errors = validate(recipe_map, inventory_item_map)
    warnings = find_orphan_inventory_keys(recipe_map, inventory_item_map)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    print("recipe_map validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
