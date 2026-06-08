"""Update canonical catalog fixture so English-only item names that have a
bilingual counterpart in a live merchant's catalog get renamed to match.

Why: the canonical fixture was assembled inconsistently — most cold drinks were
added with bilingual names (e.g., "Matcha Latte 抹茶拿鐵") but the hot variants
(and a handful of others) were added English-only ("Hot Matcha Latte"). Live
merchants whose catalogs are consistently bilingual cannot match the English-only
canonical entries by name, so those sold items never get aliases.

Approach:
  1. Walk a live merchant's catalog and collect every bilingual item name,
     indexed by its English prefix (everything before the first CJK character).
  2. For every canonical variation whose item_name is purely English (no CJK)
     and has exactly one bilingual match in the live catalog, rename the
     canonical entry to the live bilingual form.
  3. Items with no live bilingual match are skipped (they're either truly
     English-only items like "Mosa Hat" / "Sticker", or net-new menu items
     that aren't in canonical at all).

Dry-run by default; pass --apply to mutate the fixture.

    ./.venv/bin/python -m scripts.bilingualize_canonical_fixture \\
        --merchant <MID> --environment production
    ./.venv/bin/python -m scripts.bilingualize_canonical_fixture \\
        --merchant <MID> --environment production --apply
"""

import argparse
import json
import sys
from pathlib import Path

from app.script_client import create_square_client_from_args

CANONICAL_FIXTURE = Path("testing/fixtures/catalog/sandbox_canonical_catalog.json")

# CJK Unified Ideographs range — covers Chinese, kanji, and most Japanese chars.
CJK_START = "一"
CJK_END = "鿿"


def split_bilingual(name):
    """Return (english_prefix, cjk_suffix) for a bilingual name, or (name, None)
    if the name has no CJK characters."""
    if not name:
        return (name, None)
    for i, ch in enumerate(name):
        if CJK_START <= ch <= CJK_END:
            return (name[:i].strip(), name[i:].strip())
    return (name, None)


def _live_bilingual_by_english_prefix(client):
    """Walk live catalog; return {casefold(english_prefix): [full_bilingual_name]}."""
    index = {}
    for item in client.catalog.list(types="ITEM"):
        item_data = getattr(item, "item_data", None)
        name = getattr(item_data, "name", None) if item_data else None
        if not name:
            continue
        english, cjk = split_bilingual(name)
        if cjk is None:
            continue  # not bilingual
        index.setdefault(english.casefold(), []).append(name)
    return index


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args, remaining = parser.parse_known_args(sys.argv[1:])

    client, _ = create_square_client_from_args(remaining)

    live_index = _live_bilingual_by_english_prefix(client)
    fixture = json.loads(CANONICAL_FIXTURE.read_text())
    variations = fixture.get("variations", {})

    renames = []  # (var_id, old_item_name, new_item_name)
    ambiguous = []  # (var_id, item_name, [live_matches])
    seen_renames_per_item_name = {}  # group multiple variations under same item_name

    for var_id, variation in variations.items():
        canon_name = variation.get("item_name")
        if not canon_name:
            continue
        _, cjk = split_bilingual(canon_name)
        if cjk is not None:
            continue  # already bilingual

        matches = live_index.get(canon_name.casefold(), [])
        # Dedupe live matches (same item can have multiple sellable variations
        # in live, all sharing the same item_name).
        unique_matches = sorted(set(matches))
        if len(unique_matches) == 1:
            new_name = unique_matches[0]
            renames.append((var_id, canon_name, new_name))
            seen_renames_per_item_name.setdefault(canon_name, set()).add(new_name)
        elif len(unique_matches) > 1:
            ambiguous.append((var_id, canon_name, unique_matches))

    print(f"\n=== RENAMES ({len(renames)} canonical variations) ===")
    # Group by source item_name so we don't print the same rename twice per item
    grouped = {}
    for var_id, old, new in renames:
        grouped.setdefault((old, new), []).append(var_id)
    for (old, new), var_ids in sorted(grouped.items()):
        print(f"  {old!r:60s} -> {new!r:60s}  ({len(var_ids)} variation{'s' if len(var_ids) > 1 else ''})")

    if ambiguous:
        print(f"\n=== AMBIGUOUS (skipped: multiple live bilingual matches) ===")
        for var_id, name, opts in ambiguous:
            print(f"  {name!r}  could be any of: {opts}")

    print(f"\nTotal renames pending: {len(renames)}")
    print(f"Unique item_name renames: {len(grouped)}")

    if not args.apply:
        print("\n(dry-run — rerun with --apply to update fixture)")
        return 0

    if not renames:
        print("\nnothing to apply.")
        return 0

    for var_id, _old, new in renames:
        variations[var_id]["item_name"] = new
    CANONICAL_FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n")
    print(f"\napplied: {CANONICAL_FIXTURE} updated")
    print("next: rerun build_merchant_binding to pick up the new matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
