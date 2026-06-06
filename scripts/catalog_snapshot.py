"""Catalog snapshot tool — export the current Square catalog to a JSON file
and replay it onto a fresh sandbox account.

This tool is for SANDBOX use only — populating fresh test accounts with the
same menu structure for TEST PRODUCTION rehearsals. Not part of the production
pipeline.

Subcommands:

  export --account <slug> [--merchant <id>] [--environment sandbox|production]
      Read the current account's catalog (CATEGORYs, MODIFIER_LISTs, MODIFIERs,
      ITEMs + their nested variations) and write
      data/catalog_snapshots/<slug>.json.

  replay --account <slug> [--merchant <id>] [--environment ...] [--apply]
      Read data/catalog_snapshots/<slug>.json and recreate the menu on the
      target account via BatchUpsertCatalogObjects. Preview by default;
      --apply to actually mutate.

Examples:

    # Export from the populated sandbox account (env-token PAT path)
    python -m scripts.catalog_snapshot export --account default_sandbox

    # Replay onto a fresh sandbox account via OAuth merchant token
    python -m scripts.catalog_snapshot replay \\
        --account default_sandbox \\
        --merchant <new-test-merchant-id> \\
        --apply

Scope (v1):
- Captures ITEM (with nested variations), MODIFIER_LIST, MODIFIER, CATEGORY.
- Skips IMAGE, TAX, DISCOUNT, custom attributes, quick-amount settings.
  References to these types are stripped on export so replay is self-contained.

v2 additions tracked separately: image sidecar files + upload-on-replay.
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.script_client import create_square_client_from_args


SNAPSHOT_DIR = Path("data/catalog_snapshots")

# Order in which we list types from Square. Determines the order objects
# appear in the snapshot file (nice for humans reading the JSON), not the
# upsert order (BatchUpsertCatalogObjects resolves dependencies server-side).
SNAPSHOT_TYPES = (
    "CATEGORY",
    "MEASUREMENT_UNIT",
    "MODIFIER_LIST",
    "MODIFIER",
    "ITEM",
)

# Fields that reference catalog objects we intentionally don't include in v1.
# Stripped during export so replay doesn't fail referencing things that don't
# exist in the target account.
OUT_OF_SCOPE_REF_FIELDS = ("image_ids", "tax_ids")

# Fields stripped during replay. Two categories rolled into one set because
# the strip mechanism is identical:
#   1. Server-assigned (Square sets these — upserts conflict if we resend):
#      updated_at, version, created_at, is_deleted
#   2. Per-source-merchant references that don't transfer across accounts:
#      present_at_all_locations, present_at_location_ids, absent_at_location_ids,
#      location_overrides (Square errors out with "unknown location id" if these
#      reference locations that don't exist in the target account).
SERVER_ASSIGNED_FIELDS = frozenset({
    "updated_at",
    "version",
    "created_at",
    "is_deleted",
    "present_at_all_locations",
    "present_at_location_ids",
    "absent_at_location_ids",
    "location_overrides",
})


def export_snapshot(client, account_slug):
    """Read catalog from `client` and write a snapshot file."""
    objects = []
    seen_ids = set()
    counts = {}

    for catalog_type in SNAPSHOT_TYPES:
        for obj in client.catalog.list(types=catalog_type):
            if obj.id in seen_ids:
                continue
            seen_ids.add(obj.id)
            payload = obj.model_dump(mode="json", exclude_none=True)
            payload = _strip_out_of_scope_refs(payload)
            objects.append(payload)
            counts[catalog_type] = counts.get(catalog_type, 0) + 1

    id_map = _build_client_id_map(objects)
    objects = [_rewrite_ids(obj, id_map) for obj in objects]

    snapshot = {
        "snapshot_meta": {
            "account_slug": account_slug,
            "exported_at": _iso_now(),
            "object_counts": counts,
            "total_objects": len(objects),
        },
        "objects": objects,
    }

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SNAPSHOT_DIR / f"{account_slug}.json"
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n")

    print(f"Exported {len(objects)} objects to {out_path}")
    for catalog_type, count in counts.items():
        print(f"  {catalog_type}: {count}")
    return 0


def replay_snapshot(client, account_slug, apply):
    """Read a snapshot file and recreate the catalog via batch_upsert."""
    path = SNAPSHOT_DIR / f"{account_slug}.json"
    if not path.exists():
        print(f"Snapshot file not found: {path}")
        return 1

    snapshot = json.loads(path.read_text())
    objects = snapshot["objects"]
    counts = snapshot["snapshot_meta"].get("object_counts", {})

    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"loaded {len(objects)} objects from {path}")
    for catalog_type, count in counts.items():
        print(f"  {catalog_type}: {count}")

    if not apply:
        print("\n(dry-run — no objects created; rerun with --apply)")
        return 0

    cleaned = [_strip_server_fields(obj) for obj in objects]
    cleaned = [_strip_nested_duplicates(obj) for obj in cleaned]
    response = client.catalog.batch_upsert(
        idempotency_key=str(uuid.uuid4()),
        batches=[{"objects": cleaned}],
    )
    id_mappings = getattr(response, "id_mappings", None) or []
    created = getattr(response, "objects", None) or []
    print(f"\nupserted: {len(created)} objects")
    print(f"id mappings (client_id -> real_id): {len(id_mappings)}")
    return 0


def _build_client_id_map(objects):
    """Build {real_id: #client_id} for every catalog object in the snapshot,
    including nested ones (e.g., ITEM_VARIATION inside an ITEM's variations).

    Walks each top-level object recursively. Any dict that has both a "type"
    and an "id" field is treated as a catalog object and gets a client-id.
    Without this recursive walk, nested ITEM_VARIATION ids leak through as
    raw Square IDs and break replay (the target account has no record of
    those ids).

    Client IDs are prefixed with # so Square's BatchUpsertCatalogObjects
    treats them as in-batch temp IDs.
    """
    mapping = {}
    used_client_ids = set()
    for obj in objects:
        _collect_object_ids(obj, mapping, used_client_ids)
    return mapping


def _collect_object_ids(node, mapping, used_client_ids):
    """Walk a JSON-like structure and add every {type, id}-shaped dict to the map."""
    if isinstance(node, dict):
        node_type = node.get("type")
        node_id = node.get("id")
        if isinstance(node_type, str) and isinstance(node_id, str) and node_id not in mapping:
            client_id = _make_client_id(node, used_client_ids)
            mapping[node_id] = client_id
            used_client_ids.add(client_id)
        for value in node.values():
            _collect_object_ids(value, mapping, used_client_ids)
    elif isinstance(node, list):
        for value in node:
            _collect_object_ids(value, mapping, used_client_ids)


def _make_client_id(obj, used_client_ids):
    """Produce a stable, unique client-side ID like #item_LATTE."""
    obj_type = obj["type"].lower()
    name = _extract_name(obj) or obj["id"]
    slug = _slugify(name)[:40] or "obj"
    candidate = f"#{obj_type}_{slug}"
    if candidate not in used_client_ids:
        return candidate
    # Tie-break on duplicate slugs (e.g., two items with same name) using a
    # short suffix derived from the real ID.
    return f"{candidate}_{obj['id'][:6].lower()}"


def _extract_name(obj):
    for data_key in (
        "item_data",
        "item_variation_data",
        "modifier_data",
        "modifier_list_data",
        "category_data",
        "measurement_unit_data",
    ):
        data = obj.get(data_key) or {}
        if data.get("name"):
            return data["name"]
    return None


def _slugify(text):
    return "".join(
        c.lower() if c.isalnum() else "_" for c in text
    ).strip("_")


def _strip_out_of_scope_refs(obj):
    """Remove fields that reference object types we don't include in v1."""
    if isinstance(obj, dict):
        return {
            k: _strip_out_of_scope_refs(v)
            for k, v in obj.items()
            if k not in OUT_OF_SCOPE_REF_FIELDS
        }
    if isinstance(obj, list):
        return [_strip_out_of_scope_refs(v) for v in obj]
    return obj


def _rewrite_ids(obj, id_map):
    """Recursively rewrite any string value that matches a known real ID."""
    if isinstance(obj, dict):
        return {k: _rewrite_ids(v, id_map) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_ids(v, id_map) for v in obj]
    if isinstance(obj, str) and obj in id_map:
        return id_map[obj]
    return obj


def _strip_server_fields(obj):
    """Remove fields Square assigns server-side so upsert doesn't conflict."""
    if isinstance(obj, dict):
        return {
            k: _strip_server_fields(v)
            for k, v in obj.items()
            if k not in SERVER_ASSIGNED_FIELDS
        }
    if isinstance(obj, list):
        return [_strip_server_fields(v) for v in obj]
    return obj


def _strip_nested_duplicates(obj):
    """Drop nested catalog objects that are also present as top-level entries.

    Square's BatchUpsertCatalogObjects rejects payloads where the same
    catalog object appears both at top-level and nested inside a parent
    (it sees the same client-id twice and errors with
    ``Object with duplicate ID``).

    In practice this happens with MODIFIERs: Square returns them both via
    ``list(types="MODIFIER")`` (top-level) and inside
    ``MODIFIER_LIST.modifier_list_data.modifiers`` (nested). We send only
    the top-level form; Square reconstructs the list↔modifier relationship
    via each MODIFIER's back-reference (``modifier_data.modifier_list_id``).
    """
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if (
                obj.get("type") == "MODIFIER_LIST"
                and k == "modifier_list_data"
                and isinstance(v, dict)
            ):
                result[k] = {
                    ik: _strip_nested_duplicates(iv)
                    for ik, iv in v.items()
                    if ik != "modifiers"
                }
            else:
                result[k] = _strip_nested_duplicates(v)
        return result
    if isinstance(obj, list):
        return [_strip_nested_duplicates(v) for v in obj]
    return obj


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    client, remaining = create_square_client_from_args(sys.argv[1:])

    parser = argparse.ArgumentParser(
        prog="catalog_snapshot",
        description=(
            "Snapshot or replay a Square catalog. Sandbox use only — "
            "populates fresh test accounts with the same menu structure."
        ),
    )
    parser.add_argument(
        "subcommand",
        choices=["export", "replay"],
        help="export reads from the current account; replay writes to it.",
    )
    parser.add_argument(
        "--account",
        required=True,
        help="snapshot file label (writes/reads data/catalog_snapshots/<slug>.json)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="(replay only) actually mutate the target catalog (default: dry-run preview)",
    )
    args = parser.parse_args(remaining)

    if args.subcommand == "export":
        return export_snapshot(client, args.account)
    return replay_snapshot(client, args.account, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
