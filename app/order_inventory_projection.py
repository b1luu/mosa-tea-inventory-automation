import json
from decimal import Decimal
from pathlib import Path


INVENTORY_ITEM_MAP_FILE = Path("data/inventory_item_map.json")
RECIPE_MAP_FILE = Path("data/recipe_map.json")


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_inventory_item_map():
    data = _load_json(INVENTORY_ITEM_MAP_FILE)
    return data.get("inventory_items", {})


def load_recipe_map():
    return _load_json(RECIPE_MAP_FILE)


def get_recipe_for_sold_variation(sold_variation_id, _seen=None):
    recipe_map = load_recipe_map()
    sold_variation_recipes = recipe_map.get("sold_variation_recipes", {})
    recipe = sold_variation_recipes.get(sold_variation_id)
    if not recipe:
        return None

    same_as_sold_variation_id = recipe.get("same_as_sold_variation_id")
    if not same_as_sold_variation_id:
        return recipe

    _seen = _seen or set()
    if sold_variation_id in _seen:
        raise ValueError(
            f"Circular same_as_sold_variation_id mapping found for '{sold_variation_id}'."
        )

    return get_recipe_for_sold_variation(
        same_as_sold_variation_id,
        _seen | {sold_variation_id},
    )


def get_tea_base_map():
    recipe_map = load_recipe_map()
    return recipe_map.get("tea_bases", {})


def get_modifier_additions_map():
    recipe_map = load_recipe_map()
    return recipe_map.get("modifier_additions", {})


def get_sugar_modifier_multipliers():
    recipe_map = load_recipe_map()
    return recipe_map.get("sugar_modifier_multipliers", {})


def get_default_sugar_config():
    recipe_map = load_recipe_map()
    return recipe_map.get("default_sugar_config")


def get_default_packaging_config():
    recipe_map = load_recipe_map()
    return recipe_map.get("default_packaging_config")


def _normalize_quantity(quantity):
    return Decimal(str(quantity))


def _resolve_recipe_ingredients(recipe, modifier_ids):
    base_ingredients = list(recipe.get("ingredients", []))
    modifier_overrides = recipe.get("modifier_overrides", {})

    if not modifier_overrides:
        return base_ingredients

    modifier_ids = modifier_ids or []
    for modifier_id in modifier_ids:
        override = modifier_overrides.get(modifier_id)
        if override:
            return base_ingredients + list(override.get("ingredients", []))

    if base_ingredients:
        return base_ingredients

    raise ValueError(
        f"No matching modifier override found for recipe '{recipe.get('drink_key')}'."
    )


def _expand_ingredients(recipe_ingredients):
    tea_bases = get_tea_base_map()
    expanded_ingredients = []

    for ingredient in recipe_ingredients:
        tea_base_key = ingredient.get("tea_base_key")
        if not tea_base_key:
            expanded_ingredients.append(ingredient)
            continue

        tea_base = tea_bases.get(tea_base_key)
        if not tea_base:
            raise ValueError(f"No tea base mapping found for key '{tea_base_key}'.")

        tea_base_ingredients = tea_base.get("ingredients", [])
        requested_amount = ingredient.get("amount")
        requested_unit = ingredient.get("unit")

        if requested_amount is None:
            expanded_ingredients.extend(tea_base_ingredients)
            continue

        if not requested_unit:
            raise ValueError(
                f"Tea base '{tea_base_key}' amount was provided without a unit."
            )

        base_units = {base_ingredient["unit"] for base_ingredient in tea_base_ingredients}
        if len(base_units) != 1 or requested_unit not in base_units:
            raise ValueError(
                f"Tea base '{tea_base_key}' cannot be scaled with unit '{requested_unit}'."
            )

        base_total_amount = sum(
            Decimal(str(base_ingredient["amount"]))
            for base_ingredient in tea_base_ingredients
        )
        if base_total_amount == 0:
            raise ValueError(f"Tea base '{tea_base_key}' has zero total amount.")

        scale_factor = Decimal(str(requested_amount)) / base_total_amount

        for base_ingredient in tea_base_ingredients:
            expanded_ingredients.append(
                {
                    **base_ingredient,
                    "amount": float(
                        Decimal(str(base_ingredient["amount"])) * scale_factor
                    ),
                }
            )

    return expanded_ingredients


def _resolve_modifier_additions(modifier_ids):
    modifier_additions = get_modifier_additions_map()
    resolved_additions = []

    for modifier_id in modifier_ids or []:
        addition = modifier_additions.get(modifier_id)
        if addition:
            resolved_additions.extend(addition.get("ingredients", []))

    return resolved_additions


def _resolve_scaled_sugar_ingredient(recipe, modifier_ids):
    sugar_config = recipe.get("sugar_config", get_default_sugar_config())
    if not sugar_config:
        return []

    sugar_modifier_multipliers = get_sugar_modifier_multipliers()
    for modifier_id in modifier_ids or []:
        multiplier = sugar_modifier_multipliers.get(modifier_id)
        if multiplier is None:
            continue

        if Decimal(str(multiplier)) == 0:
            return []

        return [
            {
                "inventory_key": sugar_config["inventory_key"],
                "amount": float(
                    Decimal(str(sugar_config["full_amount"]))
                    * Decimal(str(multiplier))
                ),
                "unit": sugar_config["unit"],
                "notes": f"Selected Sugar Level modifier: {modifier_id}.",
            }
        ]

    raise ValueError(
        f"No matching sugar modifier found for recipe '{recipe.get('drink_key')}'."
    )


def _resolve_default_packaging_ingredient():
    packaging_config = get_default_packaging_config()
    if not packaging_config:
        return []

    cup_config = packaging_config["cup"]

    return [
        {
            "inventory_key": cup_config["inventory_key"],
            "amount": cup_config["amount"],
            "unit": cup_config["unit"],
            "notes": "Default cup packaging consumption for current Sandbox projections.",
        }
    ]


def _resolve_straw_ingredient(recipe, modifier_ids):
    packaging_config = get_default_packaging_config()
    if not packaging_config:
        return []

    topping_modifier_ids = set(packaging_config.get("topping_modifier_ids", []))
    built_in_topping_recipes = set(
        packaging_config.get("recipes_with_built_in_toppings", [])
    )
    has_topping_modifier = any(
        modifier_id in topping_modifier_ids for modifier_id in (modifier_ids or [])
    )
    has_built_in_topping = recipe.get("drink_key") in built_in_topping_recipes

    straw_config = (
        packaging_config["big_straw"]
        if has_topping_modifier or has_built_in_topping
        else packaging_config["small_straw"]
    )
    return [
        {
            "inventory_key": straw_config["inventory_key"],
            "amount": straw_config["amount"],
            "unit": straw_config["unit"],
            "notes": "Default straw packaging consumption for current Sandbox projections.",
        }
    ]


def _resolve_lid_ingredient(modifier_ids):
    packaging_config = get_default_packaging_config()
    if not packaging_config:
        return []

    cream_foam_modifier_ids = set(packaging_config.get("cream_foam_modifier_ids", []))
    has_cream_foam = any(
        modifier_id in cream_foam_modifier_ids for modifier_id in (modifier_ids or [])
    )
    if not has_cream_foam:
        return []

    lid_config = packaging_config["cold_cup_lid"]
    return [
        {
            "inventory_key": lid_config["inventory_key"],
            "amount": lid_config["amount"],
            "unit": lid_config["unit"],
            "notes": "Cold cup lid packaging consumption for drinks with cream foam.",
        }
    ]


def _convert_to_inventory_unit(amount, from_unit, inventory_item):
    inventory_unit = inventory_item["unit"]
    normalized_amount = Decimal(str(amount))

    if from_unit == inventory_unit:
        return normalized_amount

    yield_conversion = inventory_item.get("yield_conversion")
    if not yield_conversion:
        raise ValueError(
            f"No unit conversion found for inventory key '{inventory_item['name']}'."
        )

    input_amount = Decimal(str(yield_conversion["input_amount"]))
    output_amount = Decimal(str(yield_conversion["output_amount"]))
    input_unit = yield_conversion["input_unit"]
    output_unit = yield_conversion["output_unit"]

    if from_unit == output_unit and inventory_unit == input_unit:
        return normalized_amount * (input_amount / output_amount)

    raise ValueError(
        "Unsupported conversion path for "
        f"inventory key '{inventory_item['name']}': {from_unit} -> {inventory_unit}."
    )


def project_line_item_usage(sold_variation_id, quantity, modifier_ids=None):
    recipe = get_recipe_for_sold_variation(sold_variation_id)
    if not recipe:
        raise ValueError(
            f"No recipe mapping found for sold variation '{sold_variation_id}'."
        )

    inventory_items = load_inventory_item_map()
    normalized_quantity = _normalize_quantity(quantity)
    projected_usage = []
    resolved_ingredients = _resolve_recipe_ingredients(recipe, modifier_ids)
    modifier_additions = _resolve_modifier_additions(modifier_ids)
    scaled_sugar_ingredients = _resolve_scaled_sugar_ingredient(recipe, modifier_ids)
    default_packaging_ingredients = _resolve_default_packaging_ingredient()
    straw_ingredients = _resolve_straw_ingredient(recipe, modifier_ids)
    lid_ingredients = _resolve_lid_ingredient(modifier_ids)
    expanded_ingredients = _expand_ingredients(
        resolved_ingredients
        + modifier_additions
        + scaled_sugar_ingredients
        + default_packaging_ingredients
        + straw_ingredients
        + lid_ingredients
    )

    for ingredient in expanded_ingredients:
        inventory_key = ingredient["inventory_key"]
        inventory_item = inventory_items.get(inventory_key)
        if not inventory_item:
            raise ValueError(
                f"No inventory item mapping found for key '{inventory_key}'."
            )

        recipe_amount = Decimal(str(ingredient["amount"]))
        recipe_unit = ingredient["unit"]
        inventory_amount_per_drink = _convert_to_inventory_unit(
            recipe_amount,
            recipe_unit,
            inventory_item,
        )
        total_amount = inventory_amount_per_drink * normalized_quantity

        projected_usage.append(
            {
                "inventory_key": inventory_key,
                "square_variation_id": inventory_item["square_variation_id"],
                "recipe_unit": recipe_unit,
                "recipe_amount": float(recipe_amount),
                "inventory_unit": inventory_item["unit"],
                "per_drink_inventory_amount": float(inventory_amount_per_drink),
                "sold_quantity": float(normalized_quantity),
                "total_amount": float(total_amount),
            }
        )

    return {
        "sold_variation_id": sold_variation_id,
        "modifier_ids": modifier_ids or [],
        "drink_key": recipe.get("drink_key"),
        "drink_name": recipe.get("drink_name"),
        "usage": projected_usage,
    }


def combine_projected_usage(projected_line_items):
    combined = {}

    for projected_line_item in projected_line_items:
        for usage in projected_line_item.get("usage", []):
            inventory_key = usage["inventory_key"]

            if inventory_key not in combined:
                combined[inventory_key] = {
                    "inventory_key": inventory_key,
                    "square_variation_id": usage["square_variation_id"],
                    "inventory_unit": usage["inventory_unit"],
                    "total_amount": Decimal("0"),
                }

            combined[inventory_key]["total_amount"] += Decimal(
                str(usage["total_amount"])
            )

    return [
        {
            **value,
            "total_amount": float(value["total_amount"]),
        }
        for value in combined.values()
    ]
