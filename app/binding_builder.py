"""Read-only catalog binding builder.

Given a target merchant's catalog snapshot and the canonical catalog snapshot,
derive a draft binding (``sold_variation_aliases`` / ``modifier_aliases`` /
``inventory_variation_ids``) purely by **name matching** — no writes to the
merchant's catalog, no custom attributes.

The match is exact-on-normalized-name and classified by which canonical target
set the matched id belongs to:

* a matched sellable variation whose canonical id is a recipe drink → sold alias
* a matched variation whose canonical id backs an inventory key  → inventory id
* a matched modifier whose canonical id is recipe-relevant         → modifier alias

Anything that does not match (e.g. ice levels, a gift card) is reported as
unmapped so an operator can confirm it is correctly ignored — the same fail-safe
posture the coverage report enforces. See
``docs/catalog-binding-and-production-transition.md``.
"""

import re

from app.binding_coverage_report import get_canonical_binding_targets
from app.order_inventory_projection import (
    load_inventory_item_map,
    load_recipe_map,
)


def _normalize_name(name):
    if not name:
        return ""
    return re.sub(r"\s+", " ", str(name)).strip().casefold()


def _normalize_variation_name(name):
    """Like _normalize_name, but also treats Square's default 'Regular' label
    as equivalent to an empty variation name.

    Background: Square's dashboard auto-assigns variation_name='Regular' when
    a merchant creates an item with one variation. Catalogs built via the API
    (including the original canonical fixture) often leave the field blank/None.
    Both forms semantically mean 'the sole variation,' so we collapse them so
    that live merchants whose catalogs were created via the dashboard match
    canonical entries that left the field blank (and vice versa).
    """
    normalized = _normalize_name(name)
    if normalized == "regular":
        return ""
    return normalized


def _variation_name_key(variation):
    return (
        _normalize_name(variation.get("item_name")),
        _normalize_variation_name(variation.get("variation_name")),
    )


def _index_canonical_variations(canonical_catalog):
    """Map normalized (item_name, variation_name) -> [canonical_variation_id]."""
    index = {}
    for variation_id, variation in canonical_catalog.get("variations", {}).items():
        index.setdefault(_variation_name_key(variation), []).append(variation_id)
    return index


def _index_canonical_modifiers(canonical_catalog, modifier_targets):
    """Map normalized modifier name -> [canonical_modifier_id], restricted to
    recipe-relevant (target) modifiers so ice/etc. never produce an alias."""
    index = {}
    for modifier_id, modifier in canonical_catalog.get("modifiers", {}).items():
        if modifier_id not in modifier_targets:
            continue
        index.setdefault(_normalize_name(modifier.get("name")), []).append(modifier_id)
    return index


def build_binding_from_catalogs(
    target_catalog,
    canonical_catalog,
    *,
    canonical_targets=None,
    inventory_item_map=None,
):
    if canonical_targets is None:
        canonical_targets = get_canonical_binding_targets()
    if inventory_item_map is None:
        inventory_item_map = load_inventory_item_map()

    sold_targets = set(canonical_targets["sold_variation_ids"])
    modifier_targets = set(canonical_targets["modifier_ids"])
    inventory_key_by_canonical_variation = {
        item["square_variation_id"]: inventory_key
        for inventory_key, item in inventory_item_map.items()
    }

    canonical_variation_index = _index_canonical_variations(canonical_catalog)
    canonical_modifier_index = _index_canonical_modifiers(
        canonical_catalog, modifier_targets
    )

    sold_variation_aliases = {}
    inventory_variation_ids = {}
    modifier_aliases = {}

    sold_matched = []
    inventory_matched = []
    unmapped_variations = []
    ambiguous_variations = []

    for live_id, variation in sorted(target_catalog.get("variations", {}).items()):
        canonical_ids = canonical_variation_index.get(_variation_name_key(variation))
        if not canonical_ids:
            unmapped_variations.append({"live_id": live_id, **variation})
            continue
        if len(canonical_ids) > 1:
            ambiguous_variations.append(
                {"live_id": live_id, "candidates": canonical_ids, **variation}
            )
        canonical_id = canonical_ids[0]

        if canonical_id in sold_targets:
            sold_variation_aliases[live_id] = canonical_id
            sold_matched.append({"live_id": live_id, "canonical_id": canonical_id, **variation})
        elif canonical_id in inventory_key_by_canonical_variation:
            inventory_key = inventory_key_by_canonical_variation[canonical_id]
            inventory_variation_ids[inventory_key] = live_id
            inventory_matched.append({"inventory_key": inventory_key, "live_id": live_id, **variation})
        else:
            # Matched a real catalog item with no recipe / not an inventory item.
            unmapped_variations.append({"live_id": live_id, **variation})

    modifier_matched = []
    unmapped_modifiers = []
    for live_id, modifier in sorted(target_catalog.get("modifiers", {}).items()):
        canonical_ids = canonical_modifier_index.get(_normalize_name(modifier.get("name")))
        if canonical_ids:
            modifier_aliases[live_id] = canonical_ids[0]
            modifier_matched.append({"live_id": live_id, "canonical_id": canonical_ids[0], **modifier})
        else:
            unmapped_modifiers.append({"live_id": live_id, **modifier})

    missing_inventory_keys = sorted(
        set(canonical_targets["inventory_keys"]) - set(inventory_variation_ids)
    )

    return {
        "mapping": {
            "sold_variation_aliases": sold_variation_aliases,
            "modifier_aliases": modifier_aliases,
            "inventory_variation_ids": inventory_variation_ids,
            "ignored_live_variation_ids": [],
        },
        "match_report": {
            "sold": {
                "matched": sold_matched,
                "unmapped_live_variations": unmapped_variations,
                "ambiguous": ambiguous_variations,
            },
            "inventory": {
                "matched": inventory_matched,
                "missing_keys": missing_inventory_keys,
            },
            "modifiers": {
                "matched": modifier_matched,
                "unmapped_live_modifiers": unmapped_modifiers,
            },
        },
    }


def build_binding_from_recipe_defaults(target_catalog, canonical_catalog):
    """Convenience wrapper using the live recipe/inventory maps as canonical."""
    return build_binding_from_catalogs(
        target_catalog,
        canonical_catalog,
        canonical_targets=get_canonical_binding_targets(),
        inventory_item_map=load_inventory_item_map(),
    )


# Re-exported so callers can build the canonical-name reference without reaching
# into binding_coverage_report directly.
__all__ = [
    "build_binding_from_catalogs",
    "build_binding_from_recipe_defaults",
    "load_recipe_map",
]
