# Catalog Modifier Model

Reference for how Square models modifiers, why our catalog has duplicated
modifiers, and how the recipe engine maps them. Written so the modifier
landscape doesn't have to be re-derived by hand each time (e.g. during
production onboarding).

Catalog snapshot described here is the **sandbox Default Test Account as of
2026-05**. Run `./.venv/bin/python -m scripts.modifier_report` to regenerate
the live picture for any connected account.

## How Square models modifiers

From Square's Catalog API:

- A **`CatalogModifier`** (e.g. "25% Sugar") is a catalog object with its own
  unique ID. It carries a single `modifier_list_id` — it belongs to exactly
  **one** modifier list.
- A **`CatalogModifierList`** (e.g. "Sugar Level") contains its modifiers as
  child objects.
- **Items attach to modifier lists** via `CatalogItemModifierListInfo`. One
  list can be shared across many items.

The load-bearing fact: **a modifier belongs to exactly one list.** There is no
global "25% Sugar" shared across lists.

## Why duplication is inherent

Because a modifier belongs to one list, offering the same option (e.g. "25%
Sugar") in two lists requires **two separate `CatalogModifier` objects, each
with its own ID**. Same human concept, different IDs. This is Square's data
model working as designed, not a bug — and not something we control, since
each merchant structures their own catalog.

## Mosa Tea's modifier lists

13 modifier lists, 41 modifier objects, 28 distinct names. The duplication is
bounded and explainable — every duplicate traces to one of the reasons below.

| List | Items | Purpose | Recipe-relevant? |
|---|---|---|---|
| `Sugar Level` (FNKSO2WQ) | 26 | Standard sugar options incl. 0% (No Sugar) | ✅ sugar multipliers |
| `Sugar Level (Minimum Sugar Required)` (HVIOJ357) | 9 | Fruit-tea variant — omits 0% because fruit teas taste bad unsweetened | ✅ sugar multipliers |
| `Toppings` (UFGMXSLM) | 35 | Main toppings list for standard drinks | ✅ ingredient/topping |
| `Toppings` (YEBOUJVK) | 2 | Toppings for the two Hot Spice Cider drinks only | ✅ ingredient/topping |
| `Tea Base` (RDHKXVEV) | 7 | Tea-base swaps (Four Seasons / Jasmine Green) | ✅ recipe override |
| `Tea Base` (2SAMXNUR) | 1 | Tea-base swaps (Genmai variants) | ✅ recipe override |
| `Cream Foam` (PCB7PO5W) | 25 | Brown Sugar / Pistachio cream foams | ✅ ingredient/foam |
| `Ice Level` (DTREF4EI) | 32 | No Ice / 25–100% Ice | ❌ ice is water, untracked |
| `Extra Matcha Shot` (DLVPNSDM) | 1 | Add an extra matcha shot | ⚠️ unmapped — see open questions |
| `Milk Base` (AOWZGBX3) | 3 | "Sub w/ Oat Milk" | ⚠️ unmapped — see open questions |
| `Sticker Selection` (3BGJWSWI) | 0 | Drink stickers (decorative) | ❌ orphaned, untracked |
| `Sticker Selection` (HRNBKKMW) | 0 | Drink stickers (decorative) | ❌ orphaned, untracked |
| `Selection` (76BWOEA3) | 0 | Stray drink-name stickers | ❌ orphaned, untracked |

## How the recipe engine maps modifiers

`data/recipe_map.json` references modifiers by **raw Square modifier ID** in
these structures:

- `sugar_modifier_multipliers` — `{modifier_id: multiplier}` (e.g. 0.0–1.0)
- `modifier_additions` — `{modifier_id: {ingredients: [...]}}` (toppings, foams)
- `default_packaging_config.topping_modifier_ids` /
  `hot_allowed_topping_modifier_ids` / `cream_foam_modifier_ids` — ID lists
- `sold_variation_recipes[*].modifier_overrides` — `{modifier_id: {...}}`
  (tea-base swaps)

Because the map keys on raw IDs, **every duplicate ID must be enumerated
separately.** Five logical sugar levels become nine entries; Boba and Lychee
Jelly each appear twice. This is the "sandbox-as-canonical" coupling on the
modifier side (see Future Direction).

## Duplication, categorized

Verified via `scripts/modifier_report.py`. Every inventory-relevant duplicate
has **all** of its IDs mapped — no silent gaps today.

- **Sugar (25/50/75/100%)** — 2 IDs each across `Sugar Level` and `Sugar Level
  (Minimum Sugar Required)`. Deliberate (fruit-tea no-0% rule). All mapped.
- **Boba, Lychee Jelly** — 2 IDs each across the two `Toppings` lists (standard
  vs hot-cider). All mapped.
- **Stickers** (Mosa Logo, Mosa Cabinet, Jelly BFFs) — 2 IDs each across the two
  `Sticker Selection` lists. Not inventory-relevant; correctly ignored.
- **Strawberry Matcha, Taiwanese Retro** — 3 IDs each (two `Sticker Selection`
  lists + the orphaned `Selection` list). These are also real drink items. Not
  inventory-relevant as modifiers; correctly ignored.

## Modifiers intentionally NOT mapped

Two reasons a modifier is unmapped:

**Correct to ignore:**
- **Ice levels** — ice is water, not tracked inventory.
- **Stickers** — decorative; no ingredient impact.

**Open questions (deliberate decision needed):**
- **`Extra Matcha Shot`** — adds matcha, but is unmapped, so ordering it does
  not deplete extra matcha. A small inventory gap if matcha cost matters.
- **`Sub w/ Oat Milk`** — swaps milk for oat milk, but is unmapped, so the order
  still depletes regular `milk` and never touches oat milk (which is not
  currently a tracked inventory item).

Whether to map these is an operator decision, analogous to the
refund-out-of-scope decision: fine to ignore if rare/low-impact, but it should
be a *documented* choice rather than a silent omission. Mapping them would be a
`data/recipe_map.json` change.

## Orphaned lists

Three modifier lists are attached to **0 items** and never reach an order:
`Selection` (76BWOEA3) and both `Sticker Selection` lists. Harmless catalog
cruft. Deletable if the Square catalog is ever tidied; they only add noise to
`unmapped_live_modifiers` in the binding coverage report.

## The modifier report tool

```bash
./.venv/bin/python -m scripts.modifier_report
```

Read-only. Shows modifier lists (with item-attachment counts + orphaned flags),
modifiers grouped by name (surfacing duplication), and each modifier's recipe
role or unmapped status. Uses the env `SQUARE_ACCESS_TOKEN`, so it reports on
whichever account that token belongs to.

## Production onboarding note

A production catalog will likely mirror this structure (same menu → same list
design) but with entirely different IDs, and may itself duplicate sugar/topping
options across lists. Before building a production binding:

1. Run `scripts.modifier_report` against the production catalog.
2. Map the inventory-relevant modifiers (sugar, toppings, foams, tea bases) into
   the binding's `modifier_aliases` — including every duplicate ID.
3. Ignore stickers / ice as we do in sandbox.
4. Decide explicitly on `Extra Matcha Shot` / `Sub w/ Oat Milk` equivalents.

The report turns this from guesswork into a small, reviewable table.

## Future direction

The raw-ID coupling is the modifier version of the sold-variation
"sandbox-as-canonical" debt. The long-term fix is canonical modifier keys
(`modifier:sugar_25`, `topping:boba`) with the binding's `modifier_aliases`
collapsing the many live IDs → one canonical key (N:1). This shrinks the recipe
map (9 sugar entries → 5), makes the production mapping a small named table
rather than an ID-to-ID enumeration where typos hide, and decouples the recipe
namespace from any single catalog incarnation. It is a maintainability project,
not a production prerequisite — the current ID-keyed model works.
