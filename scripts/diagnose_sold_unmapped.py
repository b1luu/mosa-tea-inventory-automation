"""Diagnostic: classify why each sold (sellable) variation in the live catalog
didn't get a sold_variation_alias entry.

Categories:
  A. MAPPED                    — already in the draft binding (the 7 winners)
  B. ITEM_NAME_MATCH_VAR_DIFF  — canonical has an item with the same item_name,
                                  but no variation matches (variation_name diff,
                                  bilingual punctuation diff, etc.). Likely
                                  fixable by renaming the live variation OR
                                  adding a canonical variation alias.
  C. NO_CANONICAL_ITEM         — canonical fixture has no item with this name.
                                  Needs to be added to the fixture + a recipe
                                  added to recipe_map.

Pass --draft-binding to point at the upserted binding JSON (defaults to the
production v1 draft path used in the rollout).
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from app.script_client import create_square_client_from_args


DEFAULT_DRAFT = "data/bindings/draft_mosa_tea_prod_v1.json"
DEFAULT_FIXTURE = "testing/fixtures/catalog/sandbox_canonical_catalog.json"


def _norm(s):
    """Same normalization the binding builder uses (case + whitespace fold)."""
    return (s or "").strip().casefold()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft-binding", default=DEFAULT_DRAFT)
    parser.add_argument("--canonical-fixture", default=DEFAULT_FIXTURE)
    args, remaining = parser.parse_known_args()

    client, _ = create_square_client_from_args(remaining)

    draft = json.loads(Path(args.draft_binding).read_text())
    mapped_live_ids = set(draft.get("sold_variation_aliases", {}).keys())

    fixture = json.loads(Path(args.canonical_fixture).read_text())
    canonical_variations = fixture.get("variations", {})

    # Build canonical lookups
    canon_by_item_name = defaultdict(list)  # norm(item_name) -> [(item_name, variation_name)]
    canon_pairs = set()                     # set of (norm(item_name), norm(variation_name))
    for v in canonical_variations.values():
        item_name = v.get("item_name")
        var_name = v.get("variation_name") or ""
        # Only consider sellable items as recipe candidates
        if not v.get("sellable", True):
            continue
        canon_by_item_name[_norm(item_name)].append((item_name, var_name))
        canon_pairs.add((_norm(item_name), _norm(var_name)))

    # Walk live catalog
    a_mapped = []
    b_var_diff = []       # (live_item_name, live_var_name, canonical_variations_for_that_item)
    c_no_canonical = []   # (live_item_name, live_var_name)

    for item in client.catalog.list(types="ITEM"):
        item_data = getattr(item, "item_data", None)
        if not item_data:
            continue
        item_name = item_data.name
        for v in (item_data.variations or []):
            vd = v.item_variation_data
            if not vd:
                continue
            if not vd.sellable:
                continue  # backend inventory items — diagnosed separately
            var_name = vd.name or ""
            if v.id in mapped_live_ids:
                a_mapped.append((item_name, var_name))
                continue
            canon_options = canon_by_item_name.get(_norm(item_name))
            if canon_options:
                b_var_diff.append((item_name, var_name, canon_options))
            else:
                c_no_canonical.append((item_name, var_name))

    print(f"\n=== A. MAPPED (already deducting): {len(a_mapped)} ===")
    for name, vn in sorted(a_mapped):
        print(f"  {name}  /  {vn!r}")

    print(f"\n=== B. ITEM_NAME MATCH, VARIATION_NAME DIFF: {len(b_var_diff)} ===")
    print("    (canonical has an item with this name, just a different variation)")
    print("    (fix: rename live variation OR add alias to canonical fixture)\n")
    for name, vn, opts in sorted(b_var_diff):
        canon_vars = ", ".join(f"{cn!r}" for _, cn in opts)
        print(f"  {name}  /  live={vn!r}  vs  canonical variations: [{canon_vars}]")

    print(f"\n=== C. NO CANONICAL ITEM (completely new): {len(c_no_canonical)} ===")
    print("    (canonical fixture has no item with this name at all)")
    print("    (fix: add to canonical fixture + add recipe to recipe_map)\n")
    for name, vn in sorted(c_no_canonical):
        print(f"  {name}  /  {vn!r}")

    print(
        f"\n=== TOTAL ===\n"
        f"  A. MAPPED:              {len(a_mapped)}\n"
        f"  B. var_name diff:       {len(b_var_diff)}  (potentially easy wins)\n"
        f"  C. unknown to canonical:{len(c_no_canonical)}  (need recipe_map work)\n"
        f"  sellable items total:   {len(a_mapped) + len(b_var_diff) + len(c_no_canonical)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
