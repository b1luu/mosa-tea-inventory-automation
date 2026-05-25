"""Generate the catalog fixtures used by the read-only binding-builder demo.

Run once (needs sandbox read access) to refresh the committed fixtures:

    ./.venv/bin/python -m scripts.generate_demo_binding_fixtures

It pulls the live sandbox catalog (which *is* the canonical catalog) and writes
two snapshots in the same shape as
``app.binding_coverage_report._load_live_catalog_snapshot``:

* ``sandbox_canonical_catalog.json`` — the canonical reference (real ids + names).
* ``simulated_production_catalog.json`` — a stand-in for a new merchant's
  catalog: identical names, deterministically re-issued ids, so the builder has
  to generate real aliases (the sandbox's own ids would need none).

The demo then runs fully offline against these committed fixtures.
"""

import json
from pathlib import Path

from app.client import create_square_client


FIXTURE_DIR = Path("testing/fixtures/catalog")
CANONICAL_FILE = FIXTURE_DIR / "sandbox_canonical_catalog.json"
SIMULATED_FILE = FIXTURE_DIR / "simulated_production_catalog.json"

# One sellable item the canonical menu does not have, to show the coverage
# report correctly flagging an unmapped (but non-blocking) live item.
EXTRA_SIMULATED_VARIATION = {
    "id": "PRODSIM-V-EXTRA-GIFTCARD",
    "item_name": "Mosa Gift Card",
    "variation_name": "$25",
    "sellable": True,
    "stockable": False,
}


def _pull_canonical_snapshot():
    client = create_square_client()
    variation_map = {}
    modifier_map = {}

    for item in client.catalog.list(types="ITEM"):
        item_data = getattr(item, "item_data", None)
        item_name = getattr(item_data, "name", None)
        for variation in getattr(item_data, "variations", None) or []:
            variation_data = getattr(variation, "item_variation_data", None)
            variation_map[variation.id] = {
                "id": variation.id,
                "item_name": item_name,
                "variation_name": (
                    getattr(variation_data, "name", None)
                    or getattr(variation, "name", None)
                ),
                "sellable": getattr(variation_data, "sellable", None),
                "stockable": getattr(variation_data, "stockable", None),
            }

    for modifier in client.catalog.list(types="MODIFIER"):
        modifier_data = getattr(modifier, "modifier_data", None)
        modifier_map[modifier.id] = {
            "id": modifier.id,
            "name": getattr(modifier_data, "name", None)
            or getattr(modifier, "name", None),
            "modifier_list_id": getattr(modifier_data, "modifier_list_id", None),
        }

    return {"variations": variation_map, "modifiers": modifier_map}


def _simulate_production_catalog(canonical):
    """Re-issue every id, keep every name. Models a new merchant whose menu
    mirrors ours but lives under entirely different catalog ids."""
    variations = {}
    for index, (_, variation) in enumerate(sorted(canonical["variations"].items()), 1):
        new_id = f"PRODSIM-V-{index:04d}"
        variations[new_id] = {**variation, "id": new_id}

    modifiers = {}
    for index, (_, modifier) in enumerate(sorted(canonical["modifiers"].items()), 1):
        new_id = f"PRODSIM-M-{index:04d}"
        new_list_id = (
            f"PRODSIM-ML-{modifier['modifier_list_id']}"
            if modifier.get("modifier_list_id")
            else None
        )
        modifiers[new_id] = {**modifier, "id": new_id, "modifier_list_id": new_list_id}

    variations[EXTRA_SIMULATED_VARIATION["id"]] = dict(EXTRA_SIMULATED_VARIATION)
    return {"variations": variations, "modifiers": modifiers}


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(payload['variations'])} variations, {len(payload['modifiers'])} modifiers)")


def main():
    canonical = _pull_canonical_snapshot()
    simulated = _simulate_production_catalog(canonical)
    _write(CANONICAL_FILE, canonical)
    _write(SIMULATED_FILE, simulated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
