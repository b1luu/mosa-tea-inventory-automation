"""Build a draft catalog binding for a merchant by name-matching their live
Square catalog against a committed canonical reference catalog. Writes a JSON
file in the shape ``scripts/upsert_merchant_catalog_binding`` expects as its
``--mapping-file``.

Read-only against Square: only walks the live catalog (``catalog.list``); does
not modify any catalog objects. Authenticates via the merchant's OAuth token
(looked up from DynamoDB + Secrets Manager) — same path the rest of the
``--merchant``-aware tooling uses.

Usage:

    python -m scripts.build_merchant_binding \\
        --environment sandbox \\
        --merchant-id <merchant_id> \\
        --output-file data/bindings/draft_<merchant>_v1.json \\
        [--canonical-file testing/fixtures/catalog/sandbox_canonical_catalog.json]

The default canonical fixture is committed to the repo and produced by
``scripts.generate_demo_binding_fixtures``. Refresh it if Default Test Account's
catalog has materially changed (rare).

Pipeline (typical):

    python -m scripts.build_merchant_binding ... --output-file draft.json
    # review draft.json + the printed match report
    python -m scripts.upsert_merchant_catalog_binding ... --mapping-file draft.json --version 1
    python -m scripts.approve_merchant_catalog_binding ... --version 1
"""

import argparse
import json
from pathlib import Path

from app.binding_builder import build_binding_from_catalogs
from app.binding_coverage_report import _load_live_catalog_snapshot
from app.json_utils import to_jsonable


DEFAULT_CANONICAL_FILE = Path("testing/fixtures/catalog/sandbox_canonical_catalog.json")


def build_merchant_binding(environment, merchant_id, canonical_file):
    """Fetch live catalog, build a draft binding by name-matching, return
    (mapping_dict, match_report)."""
    canonical_path = Path(canonical_file)
    if not canonical_path.exists():
        raise FileNotFoundError(f"Canonical catalog file not found: {canonical_path}")

    canonical_catalog = json.loads(canonical_path.read_text(encoding="utf-8"))
    live_catalog = _load_live_catalog_snapshot(environment, merchant_id)
    result = build_binding_from_catalogs(live_catalog, canonical_catalog)
    return result["mapping"], result["match_report"], live_catalog


def _print_summary(mapping, report, live_catalog, canonical_catalog_counts):
    print(f"Canonical reference: {canonical_catalog_counts['variations']} variations, "
          f"{canonical_catalog_counts['modifiers']} modifiers")
    print(f"Live merchant catalog: {len(live_catalog['variations'])} variations, "
          f"{len(live_catalog['modifiers'])} modifiers")
    print()
    print("Draft binding mapping:")
    print(f"  sold_variation_aliases:   {len(mapping['sold_variation_aliases'])}")
    print(f"  modifier_aliases:         {len(mapping['modifier_aliases'])}")
    print(f"  inventory_variation_ids:  {len(mapping['inventory_variation_ids'])}")
    print()
    print("Match report:")
    print(f"  sold matched:             {len(report['sold']['matched'])}")
    print(f"  sold unmapped:            {len(report['sold']['unmapped_live_variations'])}")
    print(f"  sold ambiguous:           {len(report['sold']['ambiguous'])}")
    print(f"  inventory matched:        {len(report['inventory']['matched'])}")
    print(f"  inventory missing keys:   {len(report['inventory']['missing_keys'])}")
    print(f"  modifier matched:         {len(report['modifiers']['matched'])}")
    print(f"  modifier unmapped:        {len(report['modifiers']['unmapped_live_modifiers'])}")

    if report["inventory"]["missing_keys"]:
        print()
        print("Missing inventory keys (would block coverage approval):")
        for key in report["inventory"]["missing_keys"][:10]:
            print(f"    - {key}")
        remaining = len(report["inventory"]["missing_keys"]) - 10
        if remaining > 0:
            print(f"    ... and {remaining} more")

    if report["sold"]["ambiguous"]:
        print()
        print("Ambiguous sold variations (more than one canonical match — needs manual review):")
        for entry in report["sold"]["ambiguous"][:5]:
            name = entry.get("item_name", "?")
            variation = entry.get("variation_name", "")
            candidates = entry.get("candidates", [])
            print(f"    - {name} / {variation} -> {candidates}")


def main():
    parser = argparse.ArgumentParser(
        prog="build_merchant_binding",
        description=(
            "Build a draft catalog binding for a merchant by name-matching "
            "their live catalog against a canonical reference. Read-only on "
            "the merchant's catalog; the output JSON feeds "
            "upsert_merchant_catalog_binding."
        ),
    )
    parser.add_argument(
        "--environment",
        required=True,
        choices=["sandbox", "production"],
        help="Square environment (matches the env where the merchant OAuth token lives).",
    )
    parser.add_argument(
        "--merchant-id",
        required=True,
        help="Merchant's Square merchant_id (e.g. ML9NYNDBN9G6X).",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Path to write the draft binding mapping JSON.",
    )
    parser.add_argument(
        "--canonical-file",
        type=Path,
        default=DEFAULT_CANONICAL_FILE,
        help=f"Canonical catalog snapshot JSON (default: {DEFAULT_CANONICAL_FILE}).",
    )
    args = parser.parse_args()

    try:
        mapping, report, live_catalog = build_merchant_binding(
            args.environment, args.merchant_id, args.canonical_file
        )
    except FileNotFoundError as exc:
        print(str(exc))
        return 1

    out_path = Path(args.output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(to_jsonable(mapping), indent=2) + "\n",
        encoding="utf-8",
    )

    canonical = json.loads(Path(args.canonical_file).read_text(encoding="utf-8"))
    canonical_counts = {
        "variations": len(canonical.get("variations", {})),
        "modifiers": len(canonical.get("modifiers", {})),
    }
    print(f"Wrote draft binding mapping to {out_path}")
    print()
    _print_summary(mapping, report, live_catalog, canonical_counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
