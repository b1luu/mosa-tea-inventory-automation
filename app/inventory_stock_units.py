from decimal import Decimal

from app.order_inventory_projection import load_inventory_item_map


def has_stock_unit_mapping(inventory_key):
    inventory_item = load_inventory_item_map()[inventory_key]
    return bool(
        inventory_item.get("stock_unit")
        and inventory_item.get("stock_unit_size") is not None
    )


def convert_inventory_amount_to_stock_unit(inventory_key, amount):
    inventory_item = load_inventory_item_map()[inventory_key]
    stock_unit = inventory_item.get("stock_unit")
    stock_unit_size = inventory_item.get("stock_unit_size")
    stock_unit_size_unit = inventory_item.get("stock_unit_size_unit")

    if not stock_unit or stock_unit_size is None:
        raise ValueError(f"No stock-unit mapping found for inventory key '{inventory_key}'.")
    if stock_unit_size_unit != inventory_item["unit"]:
        raise ValueError(f"Unsupported stock-unit conversion for inventory key '{inventory_key}'.")

    normalized_amount = Decimal(str(amount))
    stock_amount = normalized_amount / Decimal(str(stock_unit_size))
    return {
        "inventory_key": inventory_key,
        "inventory_unit": inventory_item["unit"],
        "inventory_amount": float(normalized_amount),
        "stock_unit": stock_unit,
        "stock_unit_amount": float(stock_amount),
    }


def summarize_combined_usage_in_display_units(combined_usage):
    summarized = []

    for usage in combined_usage:
        inventory_key = usage["inventory_key"]
        if has_stock_unit_mapping(inventory_key):
            converted = convert_inventory_amount_to_stock_unit(
                inventory_key,
                usage["total_amount"],
            )
            summarized.append(
                {
                    "inventory_key": inventory_key,
                    "display_unit": converted["stock_unit"],
                    "display_amount": converted["stock_unit_amount"],
                    "source_inventory_unit": converted["inventory_unit"],
                    "source_inventory_amount": converted["inventory_amount"],
                }
            )
            continue

        summarized.append(
            {
                "inventory_key": inventory_key,
                "display_unit": usage["inventory_unit"],
                "display_amount": usage["total_amount"],
                "source_inventory_unit": usage["inventory_unit"],
                "source_inventory_amount": usage["total_amount"],
            }
        )

    return summarized
