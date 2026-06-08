"""Move all inventory (stock-tracked) items into one "Backend Inventory"
category and archive them — so they vanish from the active item library and the
sellable menu while their counts stay live and API-writable.

    # preview only (no changes):
    ./.venv/bin/python -m scripts.organize_backend_inventory
    # apply (writes a backup first):
    ./.venv/bin/python -m scripts.organize_backend_inventory --apply
    # revert from the backup:
    ./.venv/bin/python -m scripts.organize_backend_inventory --revert <backup.json>

Targets exactly the items backing `data/inventory_item_map.json` (resolved to
their parent items). Account-agnostic: runs against whatever SQUARE_ENVIRONMENT/
token is configured, so the same command translates sandbox -> production.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.script_client import create_square_client_from_args

CATEGORY_NAME = "Backend Inventory"
BACKUP_DIR = Path("data/backend_inventory_backups")


def _load_inventory_variation_ids():
    # Source 1: canonical inventory_item_map.json — these are the Default Test
    # Account variation IDs (the source merchant the map was built against).
    data = json.loads(Path("data/inventory_item_map.json").read_text())
    ids = {v["square_variation_id"] for v in data["inventory_items"].values()}

    # Source 2: if create_backend_inventory has been run against a different
    # merchant (e.g., production or a fresh test account), it writes the new
    # variation IDs to this file. Merge them in so this script can find items
    # in any account where create_backend_inventory was applied — not only
    # the canonical source merchant.
    captured_path = Path("data/backend_inventory_created_ids.json")
    if captured_path.exists():
        captured = json.loads(captured_path.read_text())
        ids.update(captured.values())

    return ids


def _find_inventory_items(client, inventory_variation_ids):
    """Return {item_id: CatalogObject} for items that own an inventory variation."""
    items = {}
    for item in client.catalog.list(types="ITEM"):
        item_data = getattr(item, "item_data", None)
        variations = getattr(item_data, "variations", None) or []
        if any(v.id in inventory_variation_ids for v in variations):
            items[item.id] = item
    return items


def _ensure_backend_category(client, *, apply):
    for obj in client.catalog.list(types="CATEGORY"):
        cat = getattr(obj, "category_data", None)
        if cat and getattr(cat, "name", None) == CATEGORY_NAME:
            return obj.id, False
    if not apply:
        return None, True  # would create
    resp = client.catalog.object.upsert(
        idempotency_key=str(uuid.uuid4()),
        object={"type": "CATEGORY", "id": "#backend_inv", "category_data": {"name": CATEGORY_NAME}},
    )
    return resp.catalog_object.id, True


def _current_category_id(item):
    rc = getattr(item.item_data, "reporting_category", None)
    return getattr(rc, "id", None) if rc else None


def _archive_and_recategorize(client, item, category_id):
    """Re-upsert the item in place (preserving id/version/variations), setting
    is_archived + a single Backend Inventory category."""
    payload = item.model_dump(mode="json", exclude_none=True)
    payload.pop("updated_at", None)
    item_data = payload.setdefault("item_data", {})
    item_data["is_archived"] = True
    item_data["reporting_category"] = {"id": category_id}
    item_data["categories"] = [{"id": category_id}]
    for variation in item_data.get("variations", []):
        variation.pop("updated_at", None)
    client.catalog.object.upsert(idempotency_key=str(uuid.uuid4()), object=payload)


def _verify(client, item_id, category_id):
    obj = client.catalog.object.get(object_id=item_id).object
    archived = getattr(obj.item_data, "is_archived", None)
    rc = getattr(obj.item_data, "reporting_category", None)
    return archived is True and getattr(rc, "id", None) == category_id


def run(apply, argv):
    client, _ = create_square_client_from_args(argv)
    inv_var_ids = _load_inventory_variation_ids()
    items = _find_inventory_items(client, inv_var_ids)
    category_id, category_new = _ensure_backend_category(client, apply=apply)

    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"backend category: {CATEGORY_NAME} ({'will create' if category_new and not apply else category_id})")
    print(f"target inventory items: {len(items)}\n")

    already = sum(1 for it in items.values() if getattr(it.item_data, "is_archived", None))
    for it in sorted(items.values(), key=lambda i: i.item_data.name or ""):
        flag = " [already archived]" if getattr(it.item_data, "is_archived", None) else ""
        print(f"  {it.item_data.name}{flag}  (cat {_current_category_id(it)})")
    print(f"\n{already} already archived; {len(items) - already} to change")

    if not apply:
        print("\n(dry-run — no changes made; rerun with --apply to execute)")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = BACKUP_DIR / f"backup_{stamp}.json"
    backup = {
        "category_id": category_id,
        "items": [
            {
                "item_id": it.id,
                "is_archived": bool(getattr(it.item_data, "is_archived", False)),
                "reporting_category_id": _current_category_id(it),
                "category_ids": [getattr(c, "id", None) for c in (getattr(it.item_data, "categories", None) or [])],
            }
            for it in items.values()
        ],
    }
    backup_path.write_text(json.dumps(backup, indent=2))
    print(f"\nbackup written: {backup_path}")

    ok = 0
    for it in items.values():
        try:
            _archive_and_recategorize(client, it, category_id)
            if _verify(client, it.id, category_id):
                ok += 1
            else:
                print(f"  VERIFY FAILED for {it.item_data.name} ({it.id}) — stopping")
                break
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR on {it.item_data.name} ({it.id}): {type(e).__name__}: {e} — stopping")
            break
    print(f"\napplied + verified: {ok}/{len(items)}")
    print(f"revert with:  ./.venv/bin/python -m scripts.organize_backend_inventory --revert {backup_path}")
    return 0 if ok == len(items) else 1


def revert(backup_file, argv):
    client, _ = create_square_client_from_args(argv)
    backup = json.loads(Path(backup_file).read_text())
    restored = 0
    for entry in backup["items"]:
        obj = client.catalog.object.get(object_id=entry["item_id"]).object
        payload = obj.model_dump(mode="json", exclude_none=True)
        payload.pop("updated_at", None)
        idata = payload["item_data"]
        idata["is_archived"] = entry["is_archived"]
        if entry["reporting_category_id"]:
            idata["reporting_category"] = {"id": entry["reporting_category_id"]}
        if entry["category_ids"]:
            idata["categories"] = [{"id": c} for c in entry["category_ids"] if c]
        for v in idata.get("variations", []):
            v.pop("updated_at", None)
        client.catalog.object.upsert(idempotency_key=str(uuid.uuid4()), object=payload)
        restored += 1
    print(f"reverted {restored} items from {backup_file}")
    return 0


def main():
    args = sys.argv[1:]
    # --revert takes a backup file path; strip --revert + path before passing
    # the rest (which may include --merchant / --environment) to revert().
    if "--revert" in args:
        idx = args.index("--revert")
        if idx + 1 >= len(args):
            print("Usage: --revert <backup_file>")
            return 1
        backup_file = args[idx + 1]
        revert_argv = args[:idx] + args[idx + 2 :]
        return revert(backup_file, revert_argv)
    return run(apply="--apply" in args, argv=args)


if __name__ == "__main__":
    raise SystemExit(main())
