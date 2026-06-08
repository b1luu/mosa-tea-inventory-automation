from copy import deepcopy


def _get_mapping(binding):
    if not binding:
        return {}
    return binding.get("mapping", binding)


def canonicalize_order_summary(order_summary, binding):
    """Translate live variation/modifier IDs to canonical IDs, and drop line
    items the binding explicitly marks as ignored.

    `ignored_live_variation_ids` is the merchant-curated allowlist of sold
    variations we don't want to deduct on (merch, rewards, items with no recipe
    yet). Dropping them here — before projection — lets the rest of the order
    process normally instead of blocking the whole order on a single unknown
    line item. Live variations that are neither aliased nor explicitly ignored
    still fall through to projection and (correctly) cause the order to block,
    so a forgotten recipe addition can't silently no-op.
    """
    mapping = _get_mapping(binding)
    sold_variation_aliases = mapping.get("sold_variation_aliases", {})
    modifier_aliases = mapping.get("modifier_aliases", {})
    ignored_live_variation_ids = set(mapping.get("ignored_live_variation_ids") or [])

    canonicalized = deepcopy(order_summary)
    kept_line_items = []
    dropped = []
    for line_item in canonicalized.get("line_items") or []:
        sold_variation_id = line_item.get("catalog_object_id")
        if sold_variation_id in ignored_live_variation_ids:
            dropped.append(line_item.get("name") or sold_variation_id)
            continue

        if sold_variation_id in sold_variation_aliases:
            line_item["catalog_object_id"] = sold_variation_aliases[sold_variation_id]

        for modifier in line_item.get("modifiers") or []:
            modifier_id = modifier.get("catalog_object_id")
            if modifier_id in modifier_aliases:
                modifier["catalog_object_id"] = modifier_aliases[modifier_id]

        kept_line_items.append(line_item)

    canonicalized["line_items"] = kept_line_items

    if dropped:
        # Diagnostic — appears in worker CloudWatch logs so we can audit which
        # line items were intentionally skipped per order.
        print(
            f"canonicalize_order_summary: dropped {len(dropped)} ignored "
            f"line items: {', '.join(map(repr, dropped))}"
        )

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
