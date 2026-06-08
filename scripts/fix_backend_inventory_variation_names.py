"""One-shot fix for production backend inventory variations created with the
wrong variation_name.

Context: `scripts/create_backend_inventory.py` hard-coded `variation_name="unit"`
when it should have used the canonical fixture's per-item variation_name
(`"Regular"` for 37 items, `"600 g bags"` for TGY). As a result, the binding
builder name-matched zero of the 38 production inventory items against canonical
(item_name matched, but variation_name didn't).

This script reads:
  - data/inventory_item_map.json (inventory_key -> canonical_variation_id, item_name)
  - testing/fixtures/catalog/sandbox_canonical_catalog.json (canonical variation_name)
  - data/backend_inventory_created_ids.json (production variation_id captured at create time)

For each of the 38 backend inventory items, fetches the parent ITEM from Square,
and re-upserts it with the variation_name changed to the canonical value (only
if it differs — already-correct items are skipped).

    # preview (no writes):
    ./.venv/bin/python -m scripts.fix_backend_inventory_variation_names \\
        --merchant <MID> --environment production
    # apply:
    ./.venv/bin/python -m scripts.fix_backend_inventory_variation_names \\
        --merchant <MID> --environment production --apply

Companion fix: `scripts/create_backend_inventory.py` was updated to source
variation_name from inventory_item_map.json so future merchants don't hit this.
"""

import json
import sys
import uuid
from pathlib import Path

from app.script_client import create_square_client_from_args

INVENTORY_MAP_PATH = Path("data/inventory_item_map.json")
CANONICAL_FIXTURE_PATH = Path("testing/fixtures/catalog/sandbox_canonical_catalog.json")
CAPTURED_IDS_PATH = Path("data/backend_inventory_created_ids.json")


def _load_targets():
    """Build {production_variation_id: (inventory_key, item_name, target_variation_name)}."""
    inv_map = json.loads(INVENTORY_MAP_PATH.read_text())["inventory_items"]
    fixture = json.loads(CANONICAL_FIXTURE_PATH.read_text())
    captured = json.loads(CAPTURED_IDS_PATH.read_text())

    canonical_variations = fixture.get("variations", {})
    targets = {}
    missing = []
    for key, prod_variation_id in captured.items():
        info = inv_map.get(key)
        if not info:
            missing.append(f"{key} (not in inventory_item_map.json)")
            continue
        canon_id = info["square_variation_id"]
        canon_var = canonical_variations.get(canon_id)
        if not canon_var:
            missing.append(f"{key} (canonical_id {canon_id} not in fixture)")
            continue
        targets[prod_variation_id] = (
            key,
            info["name"],
            canon_var.get("variation_name") or "Regular",
        )
    if missing:
        raise RuntimeError(f"Cannot build targets — {len(missing)} mapping gaps: {missing}")
    return targets


def _find_items_by_variation_ids(client, variation_ids):
    """Return {parent_item_id: CatalogObject} for items that own any target variation."""
    wanted = set(variation_ids)
    items = {}
    for item in client.catalog.list(types="ITEM"):
        variations = (getattr(item.item_data, "variations", None) or []) if item.item_data else []
        if any(v.id in wanted for v in variations):
            items[item.id] = item
    return items


def _rename_variation_in_payload(payload, variation_id, new_name):
    """Mutate payload['item_data']['variations'][i].item_variation_data.name in place.
    Returns the old name (or None if not found / unchanged)."""
    for variation in payload.get("item_data", {}).get("variations", []):
        if variation.get("id") == variation_id:
            data = variation.setdefault("item_variation_data", {})
            old = data.get("name")
            if old == new_name:
                return None
            data["name"] = new_name
            return old
    return None


def run(apply, argv):
    client, _ = create_square_client_from_args(argv)
    targets = _load_targets()
    items = _find_items_by_variation_ids(client, targets.keys())

    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"targets:     {len(targets)} backend inventory variations")
    print(f"found items: {len(items)} parent items in catalog\n")

    plan = []  # list of (item, variation_id, old_name, new_name)
    found_variation_ids = set()
    for item in items.values():
        for v in item.item_data.variations or []:
            if v.id not in targets:
                continue
            found_variation_ids.add(v.id)
            _, item_name, target_name = targets[v.id]
            current_name = v.item_variation_data.name if v.item_variation_data else None
            plan.append((item, v.id, current_name, target_name, item_name))

    missing_in_catalog = set(targets) - found_variation_ids
    if missing_in_catalog:
        print(f"WARNING: {len(missing_in_catalog)} target variation ids not found in catalog:")
        for vid in sorted(missing_in_catalog):
            key, name, _ = targets[vid]
            print(f"  {vid}  ({key}: {name!r})")
        print()

    changes = [p for p in plan if p[2] != p[3]]
    unchanged = [p for p in plan if p[2] == p[3]]

    for _, vid, old, new, item_name in sorted(plan, key=lambda x: x[4]):
        flag = "" if old != new else "  [already correct]"
        print(f"  {item_name:30s}  {old!r:12s} -> {new!r}{flag}")
    print(f"\n{len(changes)} to change; {len(unchanged)} already correct")

    if not apply:
        print("\n(dry-run — no changes made; rerun with --apply to execute)")
        return 0

    if not changes:
        print("\nnothing to do.")
        return 0

    # Group changes by parent item — re-upsert each item once, in case it owns
    # multiple target variations (rare, but the code handles it).
    items_to_change = {}
    for item, vid, _old, new, _item_name in changes:
        items_to_change.setdefault(item.id, item)

    applied = 0
    for item_id, item in items_to_change.items():
        payload = item.model_dump(mode="json", exclude_none=True)
        payload.pop("updated_at", None)
        for variation in payload.get("item_data", {}).get("variations", []):
            variation.pop("updated_at", None)
        renamed_any = False
        for _, vid, _old, new, _item_name in changes:
            if any(v.get("id") == vid for v in payload.get("item_data", {}).get("variations", [])):
                if _rename_variation_in_payload(payload, vid, new) is not None:
                    renamed_any = True
        if not renamed_any:
            continue
        client.catalog.object.upsert(idempotency_key=str(uuid.uuid4()), object=payload)
        applied += 1
    print(f"\napplied: {applied} items updated")
    return 0


def main():
    argv = sys.argv[1:]
    return run(apply="--apply" in argv, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
