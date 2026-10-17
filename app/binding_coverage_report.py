from app.client import create_square_client_for_merchant
from app.manual_count_sync import SUPPORTED_INVENTORY_KEYS
from app.merchant_store import (
    get_active_catalog_binding,
    get_merchant_context,
    list_catalog_bindings,
)
from app.order_inventory_projection import is_log_only_inventory_key, load_recipe_map


def get_canonical_binding_targets():
    recipe_map = load_recipe_map()
    sold_variation_recipes = recipe_map.get("sold_variation_recipes", {})
    modifier_additions = recipe_map.get("modifier_additions", {})
    sugar_modifier_multipliers = recipe_map.get("sugar_modifier_multipliers", {})
    packaging_config = recipe_map.get("default_packaging_config") or {}
    tea_bases = recipe_map.get("tea_bases", {})

    inventory_keys = set()
    modifier_ids = (
        set(modifier_additions)
        | set(sugar_modifier_multipliers)
        | set(recipe_map.get("modifier_substitutions", {}))
    )

    def collect_ingredients(ingredients):
        for ingredient in ingredients or []:
            inventory_key = ingredient.get("inventory_key")
            if inventory_key:
                inventory_keys.add(inventory_key)
            tea_base_key = ingredient.get("tea_base_key")
            if tea_base_key:
                collect_ingredients((tea_bases.get(tea_base_key) or {}).get("ingredients", []))

    for recipe in sold_variation_recipes.values():
        collect_ingredients(recipe.get("ingredients", []))
        modifier_ids.update(recipe.get("modifier_overrides", {}))
        for override in recipe.get("modifier_overrides", {}).values():
            collect_ingredients(override.get("ingredients", []))
        sugar_config = recipe.get("sugar_config")
        if sugar_config:
            inventory_keys.add(sugar_config["inventory_key"])

    for addition in modifier_additions.values():
        collect_ingredients(addition.get("ingredients", []))

    default_sugar_config = recipe_map.get("default_sugar_config")
    if default_sugar_config:
        inventory_keys.add(default_sugar_config["inventory_key"])

    for key in ("cup", "hot_cup", "small_straw", "big_straw", "cold_cup_lid", "hot_lid"):
        packaging_entry = packaging_config.get(key)
        if packaging_entry:
            inventory_keys.add(packaging_entry["inventory_key"])

    for key in (
        "topping_modifier_ids",
        "cream_foam_modifier_ids",
        "hot_allowed_topping_modifier_ids",
    ):
        modifier_ids.update(packaging_config.get(key, []))

    # Log-only ingredients have no Square item, so the binding never needs one.
    inventory_keys = {key for key in inventory_keys if not is_log_only_inventory_key(key)}

    return {
        "sold_variation_ids": set(sold_variation_recipes),
        "modifier_ids": modifier_ids,
        "inventory_keys": inventory_keys,
        # Bound and counted from the sheet, but used by no recipe.
        "count_only_inventory_keys": SUPPORTED_INVENTORY_KEYS - inventory_keys,
    }


def _normalize_binding_summary(binding):
    if not binding:
        return None
    return {
        "location_id": binding.get("location_id"),
        "version": binding.get("version"),
        "status": binding.get("status"),
        "notes": binding.get("notes"),
        "approved_at": binding.get("approved_at"),
        "updated_at": binding.get("updated_at"),
    }


def _normalize_merchant_summary(merchant_context):
    if merchant_context is None:
        return None
    return {
        "environment": merchant_context.environment,
        "merchant_id": merchant_context.merchant_id,
        "status": merchant_context.status,
        "auth_mode": merchant_context.auth_mode,
        "display_name": merchant_context.display_name,
        "selected_location_id": merchant_context.location_id,
        "writes_enabled": merchant_context.writes_enabled,
        "binding_version": merchant_context.binding_version,
    }


def _select_binding_for_report(environment, merchant_id, location_id, binding_version=None):
    bindings = list_catalog_bindings(environment, merchant_id, location_id=location_id)
    if binding_version is not None:
        for binding in bindings:
            if binding.get("version") == binding_version:
                return binding
        raise ValueError(
            f"No catalog binding version {binding_version!r} found for merchant "
            f"{merchant_id!r} at location {location_id!r}."
        )

    if bindings:
        return max(bindings, key=lambda binding: binding.get("version") or 0)

    return None


def _variation_snapshot_entry(variation, item_name):
    variation_data = getattr(variation, "item_variation_data", None)
    return {
        "id": variation.id,
        "item_name": item_name,
        "variation_name": getattr(variation_data, "name", None) or getattr(variation, "name", None),
        "sellable": getattr(variation_data, "sellable", None),
        "stockable": getattr(variation_data, "stockable", None),
    }


def _modifier_snapshot_entry(modifier):
    modifier_data = getattr(modifier, "modifier_data", None)
    return {
        "id": modifier.id,
        "name": getattr(modifier_data, "name", None) or getattr(modifier, "name", None),
        "modifier_list_id": getattr(modifier_data, "modifier_list_id", None),
    }


def _backfill_by_id(client, variation_map, modifier_map, ensure_variation_ids, ensure_modifier_ids):
    """`catalog.list` omits archived items, so any binding-referenced id missing
    from the listed snapshot is fetched directly by id (which returns archived
    objects). This is why an archived inventory item is not falsely flagged as a
    stale binding. See docs/backend-inventory-organization.md."""
    missing_variations = [vid for vid in (ensure_variation_ids or set()) if vid not in variation_map]
    missing_modifiers = [mid for mid in (ensure_modifier_ids or set()) if mid not in modifier_map]
    missing_ids = missing_variations + missing_modifiers
    if not missing_ids:
        return

    response = client.catalog.batch_get(object_ids=missing_ids, include_related_objects=True)
    related_items = {
        obj.id: obj
        for obj in (getattr(response, "related_objects", None) or [])
        if getattr(obj, "type", None) == "ITEM"
    }
    for obj in (getattr(response, "objects", None) or []):
        obj_type = getattr(obj, "type", None)
        if obj_type == "ITEM_VARIATION":
            variation_data = getattr(obj, "item_variation_data", None)
            parent = related_items.get(getattr(variation_data, "item_id", None))
            item_name = getattr(getattr(parent, "item_data", None), "name", None)
            variation_map[obj.id] = _variation_snapshot_entry(obj, item_name)
        elif obj_type == "MODIFIER":
            modifier_map[obj.id] = _modifier_snapshot_entry(obj)


def _load_live_catalog_snapshot(
    environment,
    merchant_id,
    *,
    ensure_variation_ids=None,
    ensure_modifier_ids=None,
):
    client = create_square_client_for_merchant(environment, merchant_id)
    variation_map = {}
    modifier_map = {}

    for item in client.catalog.list(types="ITEM"):
        item_data = getattr(item, "item_data", None)
        item_name = getattr(item_data, "name", None)
        for variation in (getattr(item_data, "variations", None) or []):
            variation_map[variation.id] = _variation_snapshot_entry(variation, item_name)

    for modifier in client.catalog.list(types="MODIFIER"):
        modifier_map[modifier.id] = _modifier_snapshot_entry(modifier)

    _backfill_by_id(client, variation_map, modifier_map, ensure_variation_ids, ensure_modifier_ids)

    return {
        "variations": variation_map,
        "modifiers": modifier_map,
    }


def build_binding_coverage_report(
    environment,
    merchant_id,
    location_id,
    *,
    binding_version=None,
):
    merchant_context = get_merchant_context(environment, merchant_id)
    binding = _select_binding_for_report(
        environment,
        merchant_id,
        location_id,
        binding_version=binding_version,
    )
    active_binding = get_active_catalog_binding(environment, merchant_id, location_id)

    # Backfill ids the binding references (e.g. archived inventory variations)
    # that `catalog.list` no longer returns, so they are validated by ID.
    mapping = (binding or {}).get("mapping", {})
    ensure_variation_ids = set(mapping.get("inventory_variation_ids", {}).values()) | set(
        mapping.get("sold_variation_aliases", {}).keys()
    )
    ensure_modifier_ids = set(mapping.get("modifier_aliases", {}).keys())
    live_catalog = _load_live_catalog_snapshot(
        environment,
        merchant_id,
        ensure_variation_ids=ensure_variation_ids,
        ensure_modifier_ids=ensure_modifier_ids,
    )

    return classify_binding_coverage(
        binding,
        live_catalog,
        merchant_context=merchant_context,
        active_binding=active_binding,
    )


def classify_binding_coverage(
    binding,
    live_catalog,
    *,
    merchant_context=None,
    active_binding=None,
    canonical_targets=None,
):
    """Pure coverage classification: no stores, no network.

    Given a binding and a live catalog snapshot, classify blocking issues vs
    warnings against the canonical recipe targets. Used both by
    ``build_binding_coverage_report`` (which loads the inputs) and by offline
    tooling (the binding builder demo) that supplies fixtures directly.
    """
    if canonical_targets is None:
        canonical_targets = get_canonical_binding_targets()

    mapping = (binding or {}).get("mapping", {})
    sold_variation_aliases = mapping.get("sold_variation_aliases", {})
    modifier_aliases = mapping.get("modifier_aliases", {})
    inventory_variation_ids = mapping.get("inventory_variation_ids", {})
    ignored_live_variation_ids = set(mapping.get("ignored_live_variation_ids", []))
    ignored_live_modifier_ids = set(mapping.get("ignored_live_modifier_ids", []))
    count_only_inventory_keys = canonical_targets.get("count_only_inventory_keys", set())
    inventory_live_ids = set(inventory_variation_ids.values())

    sold_unknown_targets = [
        {"live_id": live_id, "canonical_id": canonical_id}
        for live_id, canonical_id in sold_variation_aliases.items()
        if canonical_id not in canonical_targets["sold_variation_ids"]
    ]
    sold_stale_sources = [
        {"live_id": live_id, "canonical_id": canonical_id}
        for live_id, canonical_id in sold_variation_aliases.items()
        if live_id not in live_catalog["variations"]
    ]
    identity_covered_live_variations = [
        variation
        for variation_id, variation in sorted(live_catalog["variations"].items())
        if variation_id in canonical_targets["sold_variation_ids"]
        and variation_id not in inventory_live_ids
    ]
    ignored_live_variations = [
        variation
        for variation_id, variation in sorted(live_catalog["variations"].items())
        if variation_id not in sold_variation_aliases
        and variation_id not in canonical_targets["sold_variation_ids"]
        and variation_id not in inventory_live_ids
        and variation_id in ignored_live_variation_ids
    ]
    unmapped_live_variations = [
        variation
        for variation_id, variation in sorted(live_catalog["variations"].items())
        if variation_id not in sold_variation_aliases
        and variation_id not in canonical_targets["sold_variation_ids"]
        and variation_id not in inventory_live_ids
        and variation_id not in ignored_live_variation_ids
    ]

    modifier_unknown_targets = [
        {"live_id": live_id, "canonical_id": canonical_id}
        for live_id, canonical_id in modifier_aliases.items()
        if canonical_id not in canonical_targets["modifier_ids"]
    ]
    modifier_stale_sources = [
        {"live_id": live_id, "canonical_id": canonical_id}
        for live_id, canonical_id in modifier_aliases.items()
        if live_id not in live_catalog["modifiers"]
    ]
    identity_covered_live_modifiers = [
        modifier
        for modifier_id, modifier in sorted(live_catalog["modifiers"].items())
        if modifier_id in canonical_targets["modifier_ids"]
    ]
    ignored_live_modifiers = [
        modifier
        for modifier_id, modifier in sorted(live_catalog["modifiers"].items())
        if modifier_id not in modifier_aliases
        and modifier_id not in canonical_targets["modifier_ids"]
        and modifier_id in ignored_live_modifier_ids
    ]
    unmapped_live_modifiers = [
        modifier
        for modifier_id, modifier in sorted(live_catalog["modifiers"].items())
        if modifier_id not in modifier_aliases
        and modifier_id not in canonical_targets["modifier_ids"]
        and modifier_id not in ignored_live_modifier_ids
    ]

    missing_inventory_keys = sorted(
        canonical_targets["inventory_keys"] - set(inventory_variation_ids)
    )
    stale_inventory_variation_ids = [
        {"inventory_key": inventory_key, "live_variation_id": live_variation_id}
        for inventory_key, live_variation_id in sorted(inventory_variation_ids.items())
        if live_variation_id not in live_catalog["variations"]
    ]
    count_only_inventory_bindings = [
        {"inventory_key": inventory_key, "live_variation_id": live_variation_id}
        for inventory_key, live_variation_id in sorted(inventory_variation_ids.items())
        if inventory_key not in canonical_targets["inventory_keys"]
        and inventory_key in count_only_inventory_keys
    ]
    unknown_inventory_keys = [
        {"inventory_key": inventory_key, "live_variation_id": live_variation_id}
        for inventory_key, live_variation_id in sorted(inventory_variation_ids.items())
        if inventory_key not in canonical_targets["inventory_keys"]
        and inventory_key not in count_only_inventory_keys
    ]

    blocking_issue_count = sum(
        len(group)
        for group in (
            sold_unknown_targets,
            sold_stale_sources,
            modifier_unknown_targets,
            modifier_stale_sources,
            missing_inventory_keys,
            stale_inventory_variation_ids,
        )
    )
    warning_count = len(unmapped_live_variations) + len(unmapped_live_modifiers) + len(
        unknown_inventory_keys
    )

    return {
        "merchant": _normalize_merchant_summary(merchant_context),
        "binding": _normalize_binding_summary(binding),
        "active_binding": _normalize_binding_summary(active_binding),
        "summary": {
            "ready_for_approval": binding is not None and blocking_issue_count == 0,
            "blocking_issue_count": blocking_issue_count,
            "warning_count": warning_count,
            "live_variation_count": len(live_catalog["variations"]),
            "live_modifier_count": len(live_catalog["modifiers"]),
        },
        "sold_variations": {
            "binding_alias_count": len(sold_variation_aliases),
            "canonical_target_count": len(canonical_targets["sold_variation_ids"]),
            "unknown_canonical_targets": sold_unknown_targets,
            "stale_binding_sources": sold_stale_sources,
            "identity_covered_live_variations": identity_covered_live_variations,
            "ignored_live_variations": ignored_live_variations,
            "unmapped_live_variations": unmapped_live_variations,
        },
        "modifiers": {
            "binding_alias_count": len(modifier_aliases),
            "canonical_target_count": len(canonical_targets["modifier_ids"]),
            "unknown_canonical_targets": modifier_unknown_targets,
            "stale_binding_sources": modifier_stale_sources,
            "identity_covered_live_modifiers": identity_covered_live_modifiers,
            "ignored_live_modifiers": ignored_live_modifiers,
            "unmapped_live_modifiers": unmapped_live_modifiers,
        },
        "inventory": {
            "binding_count": len(inventory_variation_ids),
            "required_canonical_key_count": len(canonical_targets["inventory_keys"]),
            "missing_required_keys": missing_inventory_keys,
            "stale_live_variation_ids": stale_inventory_variation_ids,
            "count_only_inventory_keys": count_only_inventory_bindings,
            "unknown_inventory_keys": unknown_inventory_keys,
        },
    }
