"""Post initial inventory counts to a deployed manual_count_sync-batch endpoint.

Reads counts from a JSON file shaped as:
  {"tgy": 5, "matcha": 2, "boba": 3.5, ...}
keyed by inventory_key. Pulls the stock_unit from data/inventory_item_map.json
so you only have to supply the count.

Filters to SUPPORTED_INVENTORY_KEYS automatically; warns on anything skipped.

Dry-run by default (--no-apply); pass --apply to actually mutate Square counts.

Required env vars:
  OPERATOR_API_TOKEN  Bearer token for the manual-sync API

    ./.venv/bin/python -m scripts.seed_inventory_counts \\
        --counts-file data/initial_stock_counts.json \\
        --merchant-id MLXZ38BC27GAD \\
        --location-id LZ4JV6WQHPQVE \\
        --environment production \\
        --api-url https://60ohinmt7k.execute-api.us-west-2.amazonaws.com \\
        --source-reference initial-seed-2026-06-07 \\
        --apply
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

from app.manual_count_sync import SUPPORTED_INVENTORY_KEYS


def _load_inventory_map():
    return json.loads(Path("data/inventory_item_map.json").read_text())["inventory_items"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts-file", required=True)
    parser.add_argument("--merchant-id", required=True)
    parser.add_argument("--location-id", required=True)
    parser.add_argument("--environment", required=True, choices=["sandbox", "production"])
    parser.add_argument("--api-url", required=True, help="API Gateway base URL (no trailing path)")
    parser.add_argument("--source-reference", default="initial-seed")
    parser.add_argument("--apply", action="store_true", help="Mutate Square counts (default: dry-run)")
    args = parser.parse_args()

    token = os.environ.get("OPERATOR_API_TOKEN")
    if not token:
        print("ERROR: set OPERATOR_API_TOKEN env var to your production operator token", file=sys.stderr)
        return 1

    counts = json.loads(Path(args.counts_file).read_text())
    inv_map = _load_inventory_map()

    rows = []
    skipped_unsupported = []
    skipped_unknown = []
    for key, count in counts.items():
        if key not in SUPPORTED_INVENTORY_KEYS:
            skipped_unsupported.append(key)
            continue
        if key not in inv_map:
            skipped_unknown.append(key)
            continue
        rows.append(
            {
                "inventory_key": key,
                "counted_quantity": str(count),
                "counted_unit": inv_map[key]["stock_unit"],
                "source_reference": args.source_reference,
            }
        )

    print(f"=== SEED PLAN ({'APPLY' if args.apply else 'DRY-RUN'}) ===")
    print(f"  rows to post:        {len(rows)}")
    if skipped_unsupported:
        print(f"  skipped (unsupported): {skipped_unsupported}")
    if skipped_unknown:
        print(f"  skipped (unknown key): {skipped_unknown}")
    print(f"\n  payload preview (first 5):")
    for r in rows[:5]:
        print(f"    {r}")
    print()

    body = {
        "environment": args.environment,
        "merchant_id": args.merchant_id,
        "location_id": args.location_id,
        "apply_changes": args.apply,
        "rows": rows,
    }

    url = args.api_url.rstrip("/") + "/admin/api/manual-count-sync-batch"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    print(f"POST {url}")
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"status: {resp.status}")
            print(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
