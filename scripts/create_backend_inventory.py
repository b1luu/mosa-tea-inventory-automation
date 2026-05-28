"""Create the backend inventory items in a target account and capture their
variation IDs into `inventory_variation_ids` — the production inventory-side
counterpart to the organize/builder tools.

    # preview:
    ./.venv/bin/python -m scripts.create_backend_inventory
    # create + capture (writes captured ids to a file):
    ./.venv/bin/python -m scripts.create_backend_inventory --apply

Specs come from `data/inventory_item_map.json` (our ingredient vocabulary). Each
item is created with a stock-tracked, non-sellable variation; the create
response returns the new variation id, which we record directly — so we own the
ids without name-matching. Run this BEFORE archiving (build-then-archive).

IMPORTANT: this is for a GREENFIELD account (production). Do NOT --apply against
sandbox, where the real items already exist (archived, hence invisible to the
active-name guard) — you'd create duplicates. See
docs/backend-inventory-organization.md.
"""

import json
import sys
import uuid
from pathlib import Path

from app.client import create_square_client

OUTPUT_FILE = Path("data/backend_inventory_created_ids.json")


def _specs_from_inventory_map():
    data = json.loads(Path("data/inventory_item_map.json").read_text())
    return [
        {"inventory_key": key, "name": item["name"]}
        for key, item in sorted(data["inventory_items"].items())
    ]


def _active_item_names(client):
    names = {}
    for item in client.catalog.list(types="ITEM"):
        name = (getattr(item.item_data, "name", None) or "").strip().casefold()
        names[name] = item.id
    return names


def create_and_capture(client, specs):
    """Create one stock-tracked item per spec; return {inventory_key: variation_id}."""
    captured = {}
    for spec in specs:
        response = client.catalog.object.upsert(
            idempotency_key=str(uuid.uuid4()),
            object={
                "type": "ITEM",
                "id": f"#item_{spec['inventory_key']}",
                "item_data": {
                    "name": spec["name"],
                    "variations": [
                        {
                            "type": "ITEM_VARIATION",
                            "id": f"#var_{spec['inventory_key']}",
                            "item_variation_data": {
                                "name": "unit",
                                "track_inventory": True,
                                "stockable": True,
                                "sellable": False,
                                "pricing_type": "VARIABLE_PRICING",
                            },
                        }
                    ],
                },
            },
        )
        captured[spec["inventory_key"]] = response.catalog_object.item_data.variations[0].id
    return captured


def run(apply):
    client = create_square_client()
    specs = _specs_from_inventory_map()
    active_names = _active_item_names(client)

    to_create = [s for s in specs if s["name"].strip().casefold() not in active_names]
    skipped = [s for s in specs if s["name"].strip().casefold() in active_names]

    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"to create: {len(to_create)} | skipped (active item with that name already exists): {len(skipped)}")
    for spec in to_create:
        print(f"  + {spec['name']}  ({spec['inventory_key']})")
    if skipped:
        print("  skipped:", [s["name"] for s in skipped])

    if not apply:
        print("\n(dry-run — no items created; rerun with --apply)")
        return 0

    captured = create_and_capture(client, to_create)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(captured, indent=2, sort_keys=True) + "\n")
    print(f"\ncreated + captured {len(captured)} variation ids -> {OUTPUT_FILE}")
    print("next: set initial stock, build the sold-side binding, then run organize_backend_inventory --apply")
    return 0


def main():
    return run(apply="--apply" in sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
