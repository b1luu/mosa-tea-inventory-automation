"""Snapshot current Square inventory counts for every binding-mapped
inventory item, in a single batch call. Designed for deduction verification:
run before a test order, run after, diff to see what was deducted.

Reads the binding's inventory_variation_ids to discover which catalog_object_ids
to query (one call per merchant, regardless of inventory size).

    ./.venv/bin/python -m scripts.inventory_snapshot \\
        --merchant MLXZ38BC27GAD \\
        --environment production \\
        --location-id LZ4JV6WQHPQVE
"""

import argparse
import json
import sys
from decimal import Decimal

from app.client import create_square_client_for_merchant
from app.merchant_store import get_active_catalog_binding


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchant", required=True)
    parser.add_argument("--environment", required=True, choices=["sandbox", "production"])
    parser.add_argument("--location-id", required=True)
    parser.add_argument("--diff-from", help="Optional path to a prior snapshot JSON; shows deltas only")
    args = parser.parse_args()

    binding = get_active_catalog_binding(args.environment, args.merchant, args.location_id)
    if not binding:
        print("No active binding for this merchant/location", file=sys.stderr)
        return 1
    inv_map = binding["mapping"]["inventory_variation_ids"]

    # inventory_key -> live_variation_id
    key_to_id = dict(inv_map)
    id_to_key = {v: k for k, v in key_to_id.items()}

    client = create_square_client_for_merchant(args.environment, args.merchant)
    counts = {}
    for c in client.inventory.batch_get_counts(
        catalog_object_ids=list(key_to_id.values()),
        location_ids=[args.location_id],
        states=["IN_STOCK"],
    ):
        key = id_to_key.get(c.catalog_object_id)
        if key:
            counts[key] = Decimal(c.quantity or "0")

    prior = None
    if args.diff_from:
        with open(args.diff_from) as f:
            prior_data = json.load(f)
        prior = {k: Decimal(v) for k, v in prior_data["counts"].items()}

    print(f"{'inventory_key':<25}  {'current':>15}", end="")
    if prior:
        print(f"  {'prior':>15}  {'delta':>15}")
    else:
        print()
    print("-" * (43 + (32 if prior else 0)))

    for key in sorted(key_to_id):
        current = counts.get(key, Decimal("0"))
        if prior:
            p = prior.get(key, Decimal("0"))
            delta = current - p
            marker = " <-- CHANGED" if delta != 0 else ""
            print(f"{key:<25}  {str(current):>15}  {str(p):>15}  {str(delta):>15}{marker}")
        else:
            print(f"{key:<25}  {str(current):>15}")

    # Always dump JSON to stdout below the table so subsequent runs can diff
    print()
    print("=== JSON snapshot (save to file for diffing) ===")
    print(json.dumps(
        {
            "merchant_id": args.merchant,
            "location_id": args.location_id,
            "environment": args.environment,
            "counts": {k: str(v) for k, v in counts.items()},
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
