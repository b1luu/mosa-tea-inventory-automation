"""Rename backend inventory items so the Square dashboard's "Stock on hand"
column reads with context — embed the stock_unit (and per-unit size) in the
item name.

Before this:                      "TGY               78.82336 available"
After this:                       "TGY (bag, 600g)   78.82336 available"

Only mutates the item.name field. Variation IDs, stock counts, and the
binding's sold_variation_aliases / inventory_variation_ids all keep working
unchanged — the active DynamoDB binding is variation-ID-based, not name-based,
so the worker continues to deduct correctly through this rename.

CAVEAT for future rebuilds: if you later rebuild the binding via
scripts.build_merchant_binding, canonical fixture names ("TGY") won't match
the annotated live names ("TGY (bag, 600g)") — you'd either need to skip the
rebuild (existing binding is fine), or update the canonical fixture to use
the annotated names first.

Targets the 38 variation IDs in data/backend_inventory_created_ids.json (the
merchant-specific IDs captured by scripts.create_backend_inventory --apply).
Each target's parent item gets a renamed item.name; the variation_name is
left alone (so the binding's variation_name match still works).

Dry-run by default; pass --apply to mutate.

    ./.venv/bin/python -m scripts.annotate_backend_inventory_names \\
        --merchant MLXZ38BC27GAD --environment production
    ./.venv/bin/python -m scripts.annotate_backend_inventory_names \\
        --merchant MLXZ38BC27GAD --environment production --apply
"""

import json
import sys
import uuid
from pathlib import Path

from app.script_client import create_square_client_from_args

INVENTORY_MAP_PATH = Path("data/inventory_item_map.json")
CAPTURED_IDS_PATH = Path("data/backend_inventory_created_ids.json")


# Standard short units (mass/volume) attach to the size with no space
# ("600g", "3780ml"). Word-style units (straw, cup, lid, can) get a space
# and pluralize ("2250 straws", "20 cups").
_SHORT_UNITS = frozenset({"g", "kg", "mg", "ml", "l", "oz", "lb"})


def _format_size(size_display, size_unit):
    if size_unit in _SHORT_UNITS:
        return f"{size_display}{size_unit}"
    plural = size_unit if size_display == "1" else f"{size_unit}s"
    return f"{size_display} {plural}"


def _format_name(spec):
    """Build 'Name (unit, NNN size_unit)' — or 'Name (unit)' when size is redundant."""
    base = spec["name"]
    unit = spec["stock_unit"]
    size = spec.get("stock_unit_size")
    size_unit = spec.get("stock_unit_size_unit")

    # If the size unit matches the stock unit (e.g. 1 can per can), the size
    # adds no info — drop it.
    if not size or not size_unit or size_unit == unit or size == 1:
        return f"{base} ({unit})"

    # Whole-number display where possible; one decimal otherwise.
    rounded = round(float(size))
    if abs(float(size) - rounded) < 0.5:
        size_display = f"{rounded}"
    else:
        size_display = f"{float(size):.1f}"
    return f"{base} ({unit}, {_format_size(size_display, size_unit)})"


def _load_targets():
    """Build {production_variation_id: (inventory_key, target_item_name)}."""
    inv_map = json.loads(INVENTORY_MAP_PATH.read_text())["inventory_items"]
    captured = json.loads(CAPTURED_IDS_PATH.read_text())

    targets = {}
    missing = []
    for key, prod_variation_id in captured.items():
        spec = inv_map.get(key)
        if not spec:
            missing.append(key)
            continue
        targets[prod_variation_id] = (key, _format_name(spec))
    if missing:
        raise RuntimeError(
            f"Cannot build targets — {len(missing)} inventory_keys in "
            f"{CAPTURED_IDS_PATH} not present in {INVENTORY_MAP_PATH}: {missing}"
        )
    return targets


def _find_items_by_variation_ids(client, variation_ids):
    """Return {parent_item_id: CatalogObject} for items that own any target variation."""
    wanted = set(variation_ids)
    items = {}
    for item in client.catalog.list(types="ITEM"):
        variations = (
            getattr(item.item_data, "variations", None) or []
        ) if item.item_data else []
        if any(v.id in wanted for v in variations):
            items[item.id] = item
    return items


def run(apply, argv):
    client, _ = create_square_client_from_args(argv)
    targets = _load_targets()
    items = _find_items_by_variation_ids(client, targets.keys())

    # Build per-item plan: (item, old_name, new_name) for each parent item.
    plan = []
    found_variation_ids = set()
    for item in items.values():
        for v in item.item_data.variations or []:
            if v.id in targets:
                _, new_name = targets[v.id]
                plan.append((item, item.item_data.name, new_name))
                found_variation_ids.add(v.id)
                break  # one variation -> one item entry

    missing_in_catalog = set(targets) - found_variation_ids
    if missing_in_catalog:
        print(f"WARNING: {len(missing_in_catalog)} target variation ids not found in catalog:")
        for vid in sorted(missing_in_catalog):
            key, name = targets[vid]
            print(f"  {vid}  ({key}: target {name!r})")
        print()

    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"targets:    {len(targets)} backend variations")
    print(f"found items: {len(plan)} parent items in catalog\n")

    for _, old, new in sorted(plan, key=lambda p: p[1]):
        flag = "  [already correct]" if old == new else ""
        print(f"  {old!r:35s} -> {new!r}{flag}")

    changes = [p for p in plan if p[1] != p[2]]
    print(f"\n{len(changes)} to change; {len(plan) - len(changes)} already correct")

    if not apply:
        print("\n(dry-run — no changes made; rerun with --apply to execute)")
        return 0

    if not changes:
        print("\nnothing to do.")
        return 0

    applied = 0
    for item, _old, new in changes:
        payload = item.model_dump(mode="json", exclude_none=True)
        payload.pop("updated_at", None)
        payload["item_data"]["name"] = new
        for variation in payload.get("item_data", {}).get("variations", []):
            variation.pop("updated_at", None)
        client.catalog.object.upsert(idempotency_key=str(uuid.uuid4()), object=payload)
        applied += 1
    print(f"\napplied: {applied} items renamed")
    return 0


def main():
    argv = sys.argv[1:]
    return run(apply="--apply" in argv, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
