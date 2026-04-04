from copy import deepcopy


def _get_mapping(binding):
    if not binding:
        return {}
    return binding.get("mapping", binding)


def canonicalize_order_summary(order_summary, binding):
    mapping = _get_mapping(binding)
    sold_variation_aliases = mapping.get("sold_variation_aliases", {})
    modifier_aliases = mapping.get("modifier_aliases", {})

    canonicalized = deepcopy(order_summary)
    for line_item in canonicalized.get("line_items") or []:
        sold_variation_id = line_item.get("catalog_object_id")
        if sold_variation_id in sold_variation_aliases:
            line_item["catalog_object_id"] = sold_variation_aliases[sold_variation_id]

        for modifier in line_item.get("modifiers") or []:
            modifier_id = modifier.get("catalog_object_id")
            if modifier_id in modifier_aliases:
                modifier["catalog_object_id"] = modifier_aliases[modifier_id]

    return canonicalized


def resolve_inventory_variation_id(inventory_key, binding):
    mapping = _get_mapping(binding)
    inventory_variation_ids = mapping.get("inventory_variation_ids", {})
    try:
        return inventory_variation_ids[inventory_key]
    except KeyError as error:
        raise KeyError(
            f"No merchant inventory variation binding found for inventory key "
            f"{inventory_key!r}."
        ) from error
