"""Part-2 demo: rehearse onboarding a new merchant's catalog, fully offline.

    ./.venv/bin/python -m scripts.demo_binding_readiness

Loads a *simulated production* catalog (same menu as ours, different ids),
derives a binding read-only by name-matching against the canonical catalog, and
runs the real coverage classifier — printing a narrated summary suitable for a
screen recording. No network, no stores, no catalog writes; deterministic.
"""

import json
from pathlib import Path

from app.binding_builder import build_binding_from_catalogs
from app.binding_coverage_report import (
    classify_binding_coverage,
    get_canonical_binding_targets,
)


FIXTURE_DIR = Path("testing/fixtures/catalog")
CANONICAL_FILE = FIXTURE_DIR / "sandbox_canonical_catalog.json"
SIMULATED_FILE = FIXTURE_DIR / "simulated_production_catalog.json"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rule(title):
    print("\n" + "=" * 68)
    print(title)
    print("=" * 68)


def main():
    canonical = _load(CANONICAL_FILE)
    simulated = _load(SIMULATED_FILE)
    targets = get_canonical_binding_targets()

    _rule("STEP 1 — Pull the new merchant's catalog (read-only)")
    print(
        f"  live variations: {len(simulated['variations'])} | "
        f"live modifiers: {len(simulated['modifiers'])}"
    )
    print("  (ids differ entirely from ours — this is a fresh catalog)")

    _rule("STEP 2 — Auto-derive the binding by name match (no catalog writes)")
    result = build_binding_from_catalogs(
        simulated, canonical, canonical_targets=targets
    )
    mapping = result["mapping"]
    report = result["match_report"]
    required_inventory = len(targets["inventory_keys"])
    missing_inventory = len(report["inventory"]["missing_keys"])
    print(f"  sold drink aliases generated : {len(mapping['sold_variation_aliases'])}")
    print(f"  inventory keys bound          : {len(mapping['inventory_variation_ids'])}"
          f"  (required covered: {required_inventory - missing_inventory}/{required_inventory})")
    print(f"  modifier aliases generated    : {len(mapping['modifier_aliases'])}")
    print(f"  unmapped sellable items       : {len(report['sold']['unmapped_live_variations'])} (need triage)")
    print(f"  unmapped modifiers (e.g. ice) : {len(report['modifiers']['unmapped_live_modifiers'])} (expected-ignored)")
    if report["sold"]["ambiguous"]:
        print(f"  AMBIGUOUS name matches        : {len(report['sold']['ambiguous'])}")

    print("\n  sample sold alias:")
    for entry in report["sold"]["matched"][:3]:
        print(f"    {entry['live_id']}  ->  {entry['canonical_id']}   ({entry['item_name']})")
    print("  sample modifier alias:")
    for entry in report["modifiers"]["matched"][:3]:
        print(f"    {entry['live_id']}  ->  {entry['canonical_id']}   ({entry['name']})")
    print("  unmapped (correctly left out):")
    for entry in report["sold"]["unmapped_live_variations"][:3]:
        print(f"    {entry['live_id']}   ({entry.get('item_name')})")

    _rule("STEP 3 — Validate with the coverage gate")
    binding = {
        "location_id": "SIMULATED-LOCATION",
        "version": 1,
        "status": "draft",
        "mapping": mapping,
    }
    coverage = classify_binding_coverage(binding, simulated, canonical_targets=targets)
    summary = coverage["summary"]
    print(f"  ready_for_approval   : {summary['ready_for_approval']}")
    print(f"  blocking issues      : {summary['blocking_issue_count']}")
    print(f"  warnings             : {summary['warning_count']}")
    print(f"  (warnings = unmapped live items an operator confirms are ignorable)")

    _rule("RESULT")
    if summary["ready_for_approval"]:
        print("  ✅ Binding is ready to approve. Onboarding a real merchant is")
        print("     this same read-only, validated, no-catalog-writes process.")
    else:
        print("  ⚠️  Binding has blocking issues — see coverage detail above.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
