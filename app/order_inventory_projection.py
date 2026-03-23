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
    data = _load_json(RECIPE_MAP_FILE)
    return data.get("sold_variation_recipes", {})


def get_recipe_for_sold_variation(sold_variation_id):
    recipe_map = load_recipe_map()
    return recipe_map.get(sold_variation_id)


def _normalize_quantity(quantity):
    return Decimal(str(quantity))


def project_line_item_usage(sold_variation_id, quantity):
    recipe = get_recipe_for_sold_variation(sold_variation_id)
    if not recipe:
        raise ValueError(
            f"No recipe mapping found for sold variation '{sold_variation_id}'."
        )

    inventory_items = load_inventory_item_map()
    normalized_quantity = _normalize_quantity(quantity)
    projected_usage = []

    for ingredient in recipe.get("ingredients", []):
        inventory_key = ingredient["inventory_key"]
        inventory_item = inventory_items.get(inventory_key)
        if not inventory_item:
            raise ValueError(
                f"No inventory item mapping found for key '{inventory_key}'."
            )

        per_drink_amount = Decimal(str(ingredient["amount"]))
        total_amount = per_drink_amount * normalized_quantity

        projected_usage.append(
            {
                "inventory_key": inventory_key,
                "square_variation_id": inventory_item["square_variation_id"],
                "unit": ingredient["unit"],
                "per_drink_amount": float(per_drink_amount),
                "sold_quantity": float(normalized_quantity),
                "total_amount": float(total_amount),
            }
        )

    return {
        "sold_variation_id": sold_variation_id,
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
                    "unit": usage["unit"],
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
