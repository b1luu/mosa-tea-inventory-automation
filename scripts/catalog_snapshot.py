"""Catalog snapshot tool: copy a Square catalog 1:1 onto a fresh sandbox account.

Production is only ever READ: catalog.list, catalog.batch_get and inventory
count reads. Every subcommand that writes refuses to run against production or
against the production merchant tables.

Each run talks to ONE environment. Prod and sandbox use different merchant
tables and secret prefixes, chosen by environment variables, so data crosses
between them through files in data/catalog_snapshots/ (gitignored when the
slug contains "prod"):

  <slug>.json         the snapshot, plus the prod binding and prod -> client IDs
  <slug>.idmap.json   prod ID -> client ID -> sandbox ID, written by replay
  <slug>.counts.json  prod on-hand counts, written by export-counts

Subcommands:

  export --account <slug> [--merchant <id>] [--environment sandbox|production]
      Read CATEGORY, MEASUREMENT_UNIT, MODIFIER_LIST, MODIFIER and ITEM (with
      nested variations). With --merchant, also read the active binding and
      fetch by ID every object it references that catalog.list left out
      (catalog.list omits archived items), plus their parents.

  replay --account <slug> --merchant <id> [--apply] [--force]
      Recreate the snapshot on the target account with one batch_upsert and
      write the ID map. Preview by default. Refuses a target whose catalog is
      not empty unless --force: replay creates new objects every time.

  translate-binding --account <slug> --merchant <id> [--location-id <id>]
      Rewrite the prod binding through the ID map and upsert it as a DRAFT for
      the target merchant, then run the coverage report. A prod ID missing from
      the map is an error. Approve with scripts.approve_merchant_catalog_binding.

  verify --account <slug> --merchant <id>
      Export the target catalog (with the archived backfill) and compare it
      with the snapshot through the ID map, ignoring IDs, versions and
      timestamps. Exit 1 on any difference.

  export-counts --account <slug> --merchant <prod id> --environment production
      Read prod's IN_STOCK counts for the binding's inventory items.

  copy-counts --account <slug> --merchant <id> [--location-id <id>] [--apply]
      Write those counts as PHYSICAL_COUNTs to the matching target items.
      Dry run by default.

Example (1:1 prod copy):

    # prod settings in the environment
    python -m scripts.catalog_snapshot export --account mosa_prod_2026-11-19 \\
        --merchant <prod-merchant> --environment production
    # sandbox settings in the environment
    python -m scripts.catalog_snapshot replay --account mosa_prod_2026-11-19 \\
        --merchant <sandbox-merchant> --environment sandbox [--apply]

Scope:
- Captures ITEM (with nested variations), MODIFIER_LIST, MODIFIER, CATEGORY,
  MEASUREMENT_UNIT.
- Skips IMAGE, TAX, DISCOUNT, custom attributes, quick-amount settings.
  References to these types are stripped on export so replay is self-contained.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.client import create_square_client
from app.config import get_square_environment_name
from app.json_utils import to_jsonable
from app.merchant_store import (
    get_active_catalog_binding,
    get_merchant_context,
    list_catalog_bindings,
    resolve_merchant_access_token,
    upsert_catalog_binding,
)


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

# Also ignored by verify: legacy per-account IDs Square assigns on its own.
VERIFY_IGNORED_FIELDS = SERVER_ASSIGNED_FIELDS | {"catalog_v1_ids"}

# BatchUpsertCatalogObjects accepts at most 1,000 objects per batch.
MAX_UPSERT_BATCH = 1000
# BatchRetrieveCatalogObjects accepts at most 1,000 IDs per call.
MAX_BATCH_GET = 1000
# BatchChangeInventory accepts at most 100 changes per call.
MAX_INVENTORY_CHANGES = 100

# Binding mapping fields that hold catalog IDs, and where the IDs sit.
BINDING_ID_KEY_FIELDS = ("sold_variation_aliases", "modifier_aliases")
BINDING_ID_VALUE_FIELDS = ("inventory_variation_ids",)
BINDING_ID_LIST_FIELDS = ("ignored_live_variation_ids", "ignored_live_modifier_ids")

SQUARE_ID_PATTERN = re.compile(r"^[A-Z0-9]{20,32}$")

PROD_TABLE_ENV_VARS = (
    "DYNAMODB_MERCHANT_CONNECTION_TABLE",
    "DYNAMODB_MERCHANT_CATALOG_BINDING_TABLE",
    "MERCHANT_SECRET_PREFIX",
)


# ---------------------------------------------------------------- paths


def _snapshot_path(slug):
    return SNAPSHOT_DIR / f"{slug}.json"


def _idmap_path(slug):
    return SNAPSHOT_DIR / f"{slug}.idmap.json"


def _counts_path(slug):
    return SNAPSHOT_DIR / f"{slug}.counts.json"


def _load_json(path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return json.loads(path.read_text())


def _write_json(path, payload):
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


# ---------------------------------------------------------------- guards


def refuse_production_writes(environment):
    """Writes go to sandbox only: never production, never the prod tables."""
    if environment == "production":
        raise ValueError("Refusing to write: this subcommand never writes to production.")
    prod_settings = [
        name for name in PROD_TABLE_ENV_VARS if "prod" in (os.getenv(name) or "").lower()
    ]
    if prod_settings:
        raise ValueError(
            "Refusing to write: these settings point at production: "
            + ", ".join(prod_settings)
        )


def refuse_source_merchant(account_slug, merchant_id):
    """Writes never target the merchant the snapshot was exported from.

    The name-based check in refuse_production_writes catches prod settings;
    this catches the prod merchant ID itself, whatever the settings say.
    """
    path = _snapshot_path(account_slug)
    if not path.exists():
        # Without the snapshot there is no source merchant to compare against.
        raise ValueError(f"Refusing to write: snapshot not found: {path}")
    source = json.loads(path.read_text()).get("source") or {}
    if source.get("merchant_id") and source["merchant_id"] == merchant_id:
        raise ValueError(
            f"Refusing to write: {merchant_id!r} is the merchant this snapshot was "
            "exported from."
        )


def is_gitignored(path):
    """True only when git confirms the path is ignored. Errors count as not ignored."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def require_gitignored(paths):
    not_ignored = [str(p) for p in paths if not is_gitignored(p)]
    if not_ignored:
        raise ValueError(
            "Refusing to export from production: these files are not gitignored: "
            + ", ".join(not_ignored)
        )


def _target_catalog_is_empty(client):
    # catalog.list hides archived items, so a target holding only archived
    # objects looks empty here. A fresh account has none.
    for catalog_type in SNAPSHOT_TYPES:
        for _ in client.catalog.list(types=catalog_type):
            return False
    return True


# ---------------------------------------------------------------- export


def _dump(obj):
    if isinstance(obj, dict):
        return obj
    return obj.model_dump(mode="json", exclude_none=True)


def _collect_all_ids(node, found=None):
    """Every id of a {type, id}-shaped dict anywhere in the structure."""
    found = set() if found is None else found
    if isinstance(node, dict):
        if isinstance(node.get("type"), str) and isinstance(node.get("id"), str):
            found.add(node["id"])
        for value in node.values():
            _collect_all_ids(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_all_ids(value, found)
    return found


def binding_referenced_ids(mapping):
    ids = set()
    for field in BINDING_ID_KEY_FIELDS:
        ids.update((mapping.get(field) or {}).keys())
    for field in BINDING_ID_VALUE_FIELDS:
        ids.update((mapping.get(field) or {}).values())
    for field in BINDING_ID_LIST_FIELDS:
        ids.update(mapping.get(field) or [])
    return ids


def _batch_get(client, object_ids):
    objects, related = [], []
    ids = sorted(object_ids)
    for start in range(0, len(ids), MAX_BATCH_GET):
        response = client.catalog.batch_get(
            object_ids=ids[start : start + MAX_BATCH_GET],
            include_related_objects=True,
        )
        objects.extend(_dump(o) for o in (getattr(response, "objects", None) or []))
        related.extend(_dump(o) for o in (getattr(response, "related_objects", None) or []))
    return objects, related


def backfill_by_id(client, payloads, ensure_ids, max_rounds=3):
    """Fetch by ID every object in ``ensure_ids`` that the listing left out.

    catalog.list omits archived items; batch_get returns them. A variation is
    added through its parent ITEM (which nests it), a MODIFIER through itself
    plus its MODIFIER_LIST. Returns (added payloads, IDs still missing).
    """
    present = _collect_all_ids(payloads)
    wanted = set(ensure_ids) - present
    added = []
    orphan_variations = {}

    def _add(payload):
        added.append(payload)
        payloads.append(payload)
        present.update(_collect_all_ids(payload))

    for _ in range(max_rounds):
        if not wanted:
            break
        objects, related = _batch_get(client, wanted)
        parents = set()
        for payload in objects + related:
            obj_type, obj_id = payload.get("type"), payload.get("id")
            if obj_id in present:
                continue
            if obj_type == "ITEM_VARIATION":
                orphan_variations[obj_id] = payload
                parent_id = (payload.get("item_variation_data") or {}).get("item_id")
                if parent_id:
                    parents.add(parent_id)
            elif obj_type == "MODIFIER":
                _add(payload)
                list_id = (payload.get("modifier_data") or {}).get("modifier_list_id")
                if list_id:
                    parents.add(list_id)
            elif obj_type == "MODIFIER_LIST":
                # Replay drops modifiers nested in a list, so add them top-level.
                # Before the list: adding the list marks its nested IDs present.
                for modifier in (payload.get("modifier_list_data") or {}).get("modifiers") or []:
                    if modifier.get("id") not in present:
                        _add(modifier)
                _add(payload)
            elif obj_type in SNAPSHOT_TYPES:
                _add(payload)
        wanted = (parents | set(ensure_ids)) - present

    # A variation whose parent never came back is kept on its own.
    for obj_id, payload in orphan_variations.items():
        if obj_id not in present:
            _add(payload)

    return added, sorted(set(ensure_ids) - present)


def _list_catalog(client):
    payloads = []
    seen_ids = set()
    for catalog_type in SNAPSHOT_TYPES:
        for obj in client.catalog.list(types=catalog_type):
            if obj.id in seen_ids:
                continue
            seen_ids.add(obj.id)
            payloads.append(_dump(obj))
    return payloads


def _is_archived(payload):
    return bool((payload.get("item_data") or {}).get("is_archived"))


def _count_by_type(payloads):
    counts = {}
    for payload in payloads:
        counts[payload["type"]] = counts.get(payload["type"], 0) + 1
    return counts


def _print_counts(payloads, added):
    counts = _count_by_type(payloads)
    for catalog_type, count in counts.items():
        print(f"  {catalog_type}: {count}")
    items = [p for p in payloads if p["type"] == "ITEM"]
    archived = sum(1 for p in items if _is_archived(p))
    print(f"  ITEM archived: {archived} | active: {len(items) - archived}")
    if added is not None:
        print(f"  backfilled by ID: {len(added)} {_count_by_type(added)}")


def export_snapshot(client, account_slug, *, source=None):
    """Read the catalog from ``client`` and write a snapshot file.

    ``source`` ({environment, merchant_id, location_id, binding_version,
    mapping}) turns on the archived backfill and is saved for
    translate-binding and export-counts.
    """
    payloads = _list_catalog(client)

    added = None
    still_missing = []
    if source is not None:
        added, still_missing = backfill_by_id(
            client, payloads, binding_referenced_ids(source["mapping"])
        )

    payloads = [_strip_out_of_scope_refs(p) for p in payloads]
    id_map = _build_client_id_map(payloads)
    objects = [_rewrite_ids(p, id_map) for p in payloads]

    snapshot = {
        "snapshot_meta": {
            "account_slug": account_slug,
            "exported_at": _iso_now(),
            "object_counts": _count_by_type(objects),
            "total_objects": len(objects),
            "archived_items": sum(1 for p in objects if p["type"] == "ITEM" and _is_archived(p)),
        },
        "objects": objects,
    }
    if source is not None:
        snapshot["source"] = source
        snapshot["source_ids"] = id_map

    out_path = _snapshot_path(account_slug)
    _write_json(out_path, snapshot)

    print(f"Exported {len(objects)} objects to {out_path}")
    _print_counts(objects, added)
    if source is None:
        print("  (no --merchant: no binding, so no archived backfill)")
    if still_missing:
        print(f"WARNING: {len(still_missing)} binding IDs not found by ID either: {still_missing}")
        return 1
    return 0


# ---------------------------------------------------------------- replay


def _names_by_id(objects):
    names = {}

    def _walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("type"), str) and isinstance(node.get("id"), str):
                names.setdefault(node["id"], (node["type"], _extract_name(node)))
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(objects)
    return names


def build_id_map(snapshot, cleaned, id_mappings):
    """Join client IDs to the real IDs Square created and back to prod IDs.

    Returns (idmap payload, client IDs with no real ID).
    """
    client_to_real = {
        getattr(m, "client_object_id", None): getattr(m, "object_id", None)
        for m in id_mappings
    }
    prod_to_client = snapshot.get("source_ids") or {}
    client_to_prod = {client: prod for prod, client in prod_to_client.items()}
    names = _names_by_id(cleaned)

    expected = _collect_all_ids(cleaned) | set(prod_to_client.values())
    entries = []
    for client_id in sorted(expected):
        obj_type, name = names.get(client_id, (None, None))
        entries.append({
            "client_id": client_id,
            "prod_id": client_to_prod.get(client_id),
            "sandbox_id": client_to_real.get(client_id),
            "type": obj_type,
            "name": name,
        })
    missing = sorted(e["client_id"] for e in entries if not e["sandbox_id"])
    return {
        "account_slug": snapshot["snapshot_meta"]["account_slug"],
        "created_at": _iso_now(),
        "objects": entries,
    }, missing


def replay_snapshot(client, account_slug, apply, *, force=False, environment=None):
    """Read a snapshot file and recreate the catalog via batch_upsert."""
    path = _snapshot_path(account_slug)
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

    if apply:
        try:
            refuse_production_writes(environment)
        except ValueError as exc:
            print(exc)
            return 1

    empty = _target_catalog_is_empty(client)
    print(f"target catalog empty: {empty}")
    if not empty and not force:
        print(
            "Refusing to replay: the target catalog is not empty and replay creates "
            "new objects every time, so the menu would be duplicated. Use --force "
            "only if you mean to."
        )
        return 1

    cleaned = [_strip_server_fields(obj) for obj in objects]
    cleaned = [_strip_nested_duplicates(obj) for obj in cleaned]
    if len(cleaned) > MAX_UPSERT_BATCH:
        print(f"Refusing to replay: {len(cleaned)} objects exceed one batch ({MAX_UPSERT_BATCH}).")
        return 1

    if not apply:
        print("\n(dry-run — no objects created; rerun with --apply)")
        return 0

    response = client.catalog.batch_upsert(
        idempotency_key=str(uuid.uuid4()),
        batches=[{"objects": cleaned}],
    )
    id_mappings = getattr(response, "id_mappings", None) or []
    created = getattr(response, "objects", None) or []
    print(f"\nupserted: {len(created)} objects")
    print(f"id mappings (client_id -> real_id): {len(id_mappings)}")

    idmap, missing = build_id_map(snapshot, cleaned, id_mappings)
    _write_json(_idmap_path(account_slug), idmap)
    print(f"wrote {_idmap_path(account_slug)} ({len(idmap['objects'])} objects)")
    if missing:
        print(f"ERROR: {len(missing)} objects have no real ID in the response: {missing}")
        return 1
    return 0


# ---------------------------------------------------------------- binding


def _prod_to_sandbox(idmap):
    return {e["prod_id"]: e["sandbox_id"] for e in idmap["objects"] if e.get("prod_id")}


def translate_binding_mapping(mapping, prod_to_sandbox, drop_missing=()):
    """Rewrite every prod ID in a binding mapping. Raises on any unmapped ID.

    ``drop_missing`` names prod IDs to leave out instead. Each must be
    referenced by the binding and absent from the ID map; anything else is
    refused, so a typo or a live object can never be dropped. Returns
    (translated mapping, [(field, dropped id)]).
    """
    drop = set(drop_missing)
    referenced = binding_referenced_ids(mapping)
    not_referenced = sorted(drop - referenced)
    if not_referenced:
        raise ValueError(f"--drop-missing IDs the binding does not reference: {not_referenced}")
    not_missing = sorted(i for i in drop if prod_to_sandbox.get(i))
    if not_missing:
        raise ValueError(f"--drop-missing IDs that are in the ID map (not missing): {not_missing}")

    missing = set()
    dropped = []

    def _keep(field, prod_id):
        if prod_id in drop:
            dropped.append((field, prod_id))
            return False
        return True

    def _map(prod_id):
        sandbox_id = prod_to_sandbox.get(prod_id)
        if not sandbox_id:
            missing.add(prod_id)
        return sandbox_id

    translated = {}
    for field, value in mapping.items():
        if field in BINDING_ID_KEY_FIELDS:
            translated[field] = {_map(k): v for k, v in value.items() if _keep(field, k)}
        elif field in BINDING_ID_VALUE_FIELDS:
            translated[field] = {k: _map(v) for k, v in value.items() if _keep(field, v)}
        elif field in BINDING_ID_LIST_FIELDS:
            translated[field] = [_map(v) for v in value if _keep(field, v)]
        else:
            leftover = _collect_id_like_strings(value) & set(prod_to_sandbox)
            if leftover:
                raise ValueError(
                    f"Binding field {field!r} holds prod catalog IDs but is not a known "
                    f"ID field: {sorted(leftover)}"
                )
            translated[field] = value

    if missing:
        raise ValueError(
            f"{len(missing)} prod IDs in the binding are not in the ID map: {sorted(missing)}"
        )
    return translated, sorted(dropped)


def _collect_id_like_strings(node, found=None):
    found = set() if found is None else found
    if isinstance(node, dict):
        for key, value in node.items():
            _collect_id_like_strings(key, found)
            _collect_id_like_strings(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_id_like_strings(value, found)
    elif isinstance(node, str) and SQUARE_ID_PATTERN.match(node):
        found.add(node)
    return found


def translate_binding(account_slug, environment, merchant_id, location_id, drop_missing=()):
    refuse_production_writes(environment)
    snapshot = _load_json(_snapshot_path(account_slug))
    idmap = _load_json(_idmap_path(account_slug))
    source = snapshot.get("source")
    if not source:
        raise ValueError("The snapshot has no source binding; export it with --merchant.")

    location_id = location_id or _merchant_location(environment, merchant_id)
    mapping, dropped = translate_binding_mapping(
        source["mapping"], _prod_to_sandbox(idmap), drop_missing
    )
    notes = f"1:1 copy of prod binding v{source.get('binding_version')} via {account_slug}"
    if dropped:
        notes += (
            "; dropped (in the prod binding but missing from the prod catalog, deleted): "
            + ", ".join(f"{field}:{prod_id}" for field, prod_id in dropped)
        )
        for field, prod_id in dropped:
            print(f"dropping {field}: {prod_id} (missing from the prod catalog)")

    existing = list_catalog_bindings(environment, merchant_id, location_id=location_id)
    version = max((int(b.get("version") or 0) for b in existing), default=0) + 1
    upsert_catalog_binding(
        environment,
        merchant_id,
        location_id,
        version,
        mapping,
        notes=notes,
    )
    print(f"upserted DRAFT binding v{version} for {merchant_id} at {location_id}")

    report = build_coverage_report(environment, merchant_id, location_id, version)
    summary = report.get("summary", report)
    ready = summary.get("ready_for_approval")
    print(f"coverage: ready_for_approval={ready}")
    for key in ("blocking_issue_count", "warning_count"):
        if key in summary:
            print(f"  {key}: {summary[key]}")
    if not ready:
        print(json.dumps(report.get("blocking_issues", report), indent=2, default=str)[:4000])
        return 1, version
    return 0, version


def build_coverage_report(environment, merchant_id, location_id, version):
    from app.binding_coverage_report import build_binding_coverage_report

    return build_binding_coverage_report(
        environment, merchant_id, location_id, binding_version=version
    )


def _merchant_location(environment, merchant_id):
    context = get_merchant_context(environment, merchant_id)
    if not context or not context.location_id:
        raise ValueError(f"No selected location for merchant {merchant_id!r} in {environment!r}.")
    return context.location_id


# ---------------------------------------------------------------- verify


def _normalize(payload, real_to_client):
    payload = _strip_out_of_scope_refs(payload)
    payload = _rewrite_ids(payload, real_to_client)
    payload = _strip_fields(payload, VERIFY_IGNORED_FIELDS)
    return _strip_nested_duplicates(payload)


def _strip_fields(obj, fields):
    if isinstance(obj, dict):
        return {k: _strip_fields(v, fields) for k, v in obj.items() if k not in fields}
    if isinstance(obj, list):
        return [_strip_fields(v, fields) for v in obj]
    return obj


def _diff_paths(left, right, path=""):
    if isinstance(left, dict) and isinstance(right, dict):
        paths = []
        for key in sorted(set(left) | set(right)):
            sub = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                paths.append(sub)
            else:
                paths.extend(_diff_paths(left[key], right[key], sub))
        return paths
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        paths = []
        for index, (a, b) in enumerate(zip(left, right)):
            paths.extend(_diff_paths(a, b, f"{path}[{index}]"))
        return paths
    return [] if left == right else [path or "(root)"]


def compare_catalogs(snapshot_objects, target_payloads, idmap):
    """Compare snapshot objects with the target's through the ID map."""
    real_to_client = {e["sandbox_id"]: e["client_id"] for e in idmap["objects"] if e.get("sandbox_id")}
    expected = {o["id"]: _normalize(o, {}) for o in snapshot_objects}
    actual = {}
    for payload in target_payloads:
        normalized = _normalize(payload, real_to_client)
        actual[normalized["id"]] = normalized

    def _label(obj):
        return f"{obj.get('type')} {_extract_name(obj) or obj.get('id')!r}"

    report = {"missing": [], "extra": [], "different": []}
    for key, obj in expected.items():
        if key not in actual:
            report["missing"].append(_label(obj))
        elif actual[key] != obj:
            paths = _diff_paths(obj, actual[key])
            report["different"].append({
                "object": _label(obj),
                "fields": paths,
                "is_archived_changed": any(p.endswith("is_archived") for p in paths),
            })
    for key, obj in actual.items():
        if key not in expected:
            report["extra"].append(_label(obj))
    return report


def verify(client, account_slug):
    snapshot = _load_json(_snapshot_path(account_slug))
    idmap = _load_json(_idmap_path(account_slug))
    payloads = _list_catalog(client)
    sandbox_ids = {e["sandbox_id"] for e in idmap["objects"] if e.get("sandbox_id")}
    backfill_by_id(client, payloads, sandbox_ids)

    report = compare_catalogs(snapshot["objects"], payloads, idmap)
    total = sum(len(v) for v in report.values())
    print(f"snapshot objects: {len(snapshot['objects'])} | target objects: {len(payloads)}")
    _print_counts(payloads, None)
    print(
        f"missing: {len(report['missing'])} | extra: {len(report['extra'])} | "
        f"different: {len(report['different'])}"
    )
    for label in report["missing"]:
        print(f"  MISSING    {label}")
    for label in report["extra"]:
        print(f"  EXTRA      {label}")
    for diff in report["different"]:
        flag = "  (is_archived changed)" if diff["is_archived_changed"] else ""
        print(f"  DIFFERENT  {diff['object']}: {', '.join(diff['fields'])}{flag}")
    return 1 if total else 0


# ---------------------------------------------------------------- counts


def export_counts(client, account_slug):
    snapshot = _load_json(_snapshot_path(account_slug))
    source = snapshot.get("source")
    if not source:
        raise ValueError("The snapshot has no source binding; export it with --merchant.")
    inventory_ids = sorted(set(source["mapping"].get("inventory_variation_ids", {}).values()))
    counts = {object_id: "0" for object_id in inventory_ids}
    for count in client.inventory.batch_get_counts(
        catalog_object_ids=inventory_ids,
        location_ids=[source["location_id"]],
        states=["IN_STOCK"],
    ):
        counts[count.catalog_object_id] = str(count.quantity)
    _write_json(_counts_path(account_slug), {"read_at": _iso_now(), "counts": counts})
    print(f"read {len(counts)} prod counts into {_counts_path(account_slug)}")
    return 0


def copy_counts(client, account_slug, environment, location_id, apply):
    if apply:
        refuse_production_writes(environment)
    counts = _load_json(_counts_path(account_slug))["counts"]
    prod_to_sandbox = _prod_to_sandbox(_load_json(_idmap_path(account_slug)))
    missing = sorted(p for p in counts if not prod_to_sandbox.get(p))
    if missing:
        raise ValueError(f"{len(missing)} counted prod IDs are not in the ID map: {missing}")

    occurred_at = _iso_now()
    changes = [
        {
            "type": "PHYSICAL_COUNT",
            "physical_count": {
                "reference_id": f"{account_slug}:{prod_id}",
                "catalog_object_id": prod_to_sandbox[prod_id],
                "state": "IN_STOCK",
                "location_id": location_id,
                "quantity": quantity,
                "occurred_at": occurred_at,
            },
        }
        for prod_id, quantity in sorted(counts.items())
    ]
    print(f"mode: {'APPLY' if apply else 'DRY-RUN'} | {len(changes)} physical counts at {location_id}")
    for change in changes:
        count = change["physical_count"]
        print(f"  {count['catalog_object_id']}  {count['quantity']}")
    if not apply:
        print("\n(dry-run — no counts written; rerun with --apply)")
        return 0
    for start in range(0, len(changes), MAX_INVENTORY_CHANGES):
        client.inventory.batch_create_changes(
            idempotency_key=str(uuid.uuid4()),
            changes=changes[start : start + MAX_INVENTORY_CHANGES],
        )
    print(f"wrote {len(changes)} physical counts")
    return 0


# ---------------------------------------------------------------- shared helpers


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
    return _strip_fields(obj, SERVER_ASSIGNED_FIELDS)


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


# ---------------------------------------------------------------- CLI


def create_client(environment, merchant_id):
    """Square client for one environment. Production never refreshes its token:
    a refresh writes to the prod secret, and prod stays read-only here."""
    if not merchant_id:
        return create_square_client(environment_name=environment)
    access_token = resolve_merchant_access_token(
        environment,
        merchant_id,
        refresh_if_needed=environment != "production",
    )
    if not access_token:
        raise ValueError(
            f"No active Square access token for merchant {merchant_id!r} in {environment!r}."
        )
    return create_square_client(access_token=access_token, environment_name=environment)


def load_source(environment, merchant_id):
    location_id = _merchant_location(environment, merchant_id)
    binding = get_active_catalog_binding(environment, merchant_id, location_id)
    if not binding:
        raise ValueError(f"No active binding for {merchant_id!r} at {location_id!r}.")
    # DynamoDB returns numbers as Decimal, which json cannot write.
    version = binding.get("version")
    return {
        "environment": environment,
        "merchant_id": merchant_id,
        "location_id": location_id,
        "binding_version": int(version) if version is not None else None,
        "mapping": to_jsonable(binding["mapping"]),
    }


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="catalog_snapshot",
        description="Copy a Square catalog 1:1 onto a fresh sandbox account.",
    )
    parser.add_argument(
        "subcommand",
        choices=["export", "replay", "translate-binding", "verify", "export-counts", "copy-counts"],
    )
    parser.add_argument("--account", required=True, help="snapshot slug in data/catalog_snapshots/")
    parser.add_argument("--merchant")
    parser.add_argument("--environment", choices=["sandbox", "production"])
    parser.add_argument("--location-id")
    parser.add_argument("--apply", action="store_true", help="replay / copy-counts: actually write")
    parser.add_argument("--force", action="store_true", help="replay: allow a non-empty target")
    parser.add_argument(
        "--drop-missing",
        action="append",
        default=[],
        metavar="PROD_ID",
        help="translate-binding: leave out this prod ID, which must be missing from the ID map (repeatable)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    environment = args.environment or get_square_environment_name()
    print(f"environment: {environment} | merchant: {args.merchant or '(env token)'} | account: {args.account}")

    try:
        if environment == "production" and not args.merchant:
            raise ValueError("--environment production needs --merchant (no env-token fallback).")

        if args.subcommand in ("export", "export-counts") and environment == "production":
            out_path = (
                _snapshot_path(args.account)
                if args.subcommand == "export"
                else _counts_path(args.account)
            )
            require_gitignored([out_path])
        if args.subcommand == "export":
            source = load_source(environment, args.merchant) if args.merchant else None
            return export_snapshot(create_client(environment, args.merchant), args.account, source=source)
        if args.subcommand == "export-counts":
            return export_counts(create_client(environment, args.merchant), args.account)

        if not args.merchant:
            raise ValueError(f"{args.subcommand} needs --merchant for the target account.")

        writes = (
            args.subcommand == "translate-binding"
            or (args.subcommand in ("replay", "copy-counts") and args.apply)
        )
        if args.subcommand == "replay" or writes:
            refuse_production_writes(environment)
        if writes:
            refuse_source_merchant(args.account, args.merchant)

        if args.subcommand == "translate-binding":
            exit_code, _ = translate_binding(
                args.account, environment, args.merchant, args.location_id, args.drop_missing
            )
            return exit_code

        client = create_client(environment, args.merchant)
        if args.subcommand == "replay":
            return replay_snapshot(
                client, args.account, args.apply, force=args.force, environment=environment
            )
        if args.subcommand == "verify":
            return verify(client, args.account)
        location_id = args.location_id or _merchant_location(environment, args.merchant)
        return copy_counts(client, args.account, environment, location_id, args.apply)
    except (ValueError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
