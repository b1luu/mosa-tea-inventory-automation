# Catalog Binding & Production Transition

> **Status: active priority.** This is the primary open design area for taking
> the system from a sandbox-backed deployment to a real production merchant. The
> *mechanism* is already built and wired; the remaining work is populating it
> reliably for a real catalog. Read this before touching catalog binding,
> detection, or onboarding.

## TL;DR

- There are **two catalog surfaces** with opposite requirements: the **write**
  side (which inventory variation to deduct) must be **exact**; the **read /
  detection** side (which order item is which drink) is **fail-safe lookup** — a
  miss blocks an order, it can never mis-deduct.
- The **canonical-ID bridge that handles both is already implemented and runs in
  the live pipeline** (`canonicalize_order_summary`, the binding `mapping`, the
  coverage report, and the draft→approve→activate lifecycle). Canonical space =
  the sandbox catalog.
- The **only real gap** is *generating* the per-merchant maps
  (`sold_variation_aliases`, `modifier_aliases`, `inventory_variation_ids`) for a
  production merchant, instead of hand-authoring JSON.
- The recommended generator is a **binding builder driven by Square catalog
  custom attributes**: a Dashboard-visible `SELECTION` attribute for drinks and
  for inventory variations, plus name-matching-with-confirmation for modifiers.
- **Overhead crosses over** between environments: sandbox is expensive to
  *exercise* (no POS — orders must be simulated), production is expensive to
  *map* (different IDs need aliases). This is by design and it dictates the
  validation strategy: prove the engine dynamically where it's cheap (sandbox),
  gate production on a **static** coverage check (you cannot cheaply rehearse
  production detection).

## The two catalog surfaces

| Surface | Question it answers | Keyed by | Rigor required | Failure mode |
|---|---|---|---|---|
| **Detection (read)** | "Which drink is this order line / modifier?" | order `catalog_object_id`s | **Tolerant / fail-safe** | Unrecognized → order **blocked**, never mis-deducted |
| **Write (deduct)** | "Which inventory variation do I decrement?" | semantic `inventory_key` → live variation id | **Exact / locked** | Wrong target → **corrupts real stock** |

The asymmetry is the key insight: a stale or missing *detection* key is
self-protecting (it fails closed and stops the order), whereas a wrong *write*
target silently mutates the wrong stock. So detection bindings can be loose,
tag-driven, and warning-on-miss; write bindings must be validated as blocking.

Relevant code:
- Detection map: [`data/recipe_map.json`](../data/recipe_map.json), read by
  [`app/order_inventory_projection.py`](../app/order_inventory_projection.py)
  (`get_recipe_for_sold_variation`, `project_line_item_usage`).
- Write map: [`data/inventory_item_map.json`](../data/inventory_item_map.json) +
  per-merchant override
  [`app/catalog_binding_resolver.py`](../app/catalog_binding_resolver.py)
  (`resolve_inventory_variation_id`).

## What is already built (canonical-ID bridge)

The per-merchant binding's `mapping` carries four sub-maps:

```
sold_variation_aliases : { merchant_live_variation_id → canonical_variation_id }
modifier_aliases       : { merchant_live_modifier_id  → canonical_modifier_id }
inventory_variation_ids: { inventory_key → merchant_live_inventory_variation_id }
ignored_live_variation_ids: [ live_id, … ]   # explicitly "don't flag these"
```

Processing flows as a two-sided translation with **canonical recipes in the
middle**:

```
order arrives with merchant's LIVE ids
   │  canonicalize_order_summary()        ← app/order_loader.py:86 (wired)
   ▼  rewrites live → canonical via aliases
canonical ids
   │  project_line_item_usage()           ← recipe_map.json keyed by CANONICAL ids
   ▼
inventory_keys (tgy, milk, u600_cup, …)
   │  resolve_inventory_variation_id()    ← inventory_variation_ids
   ▼
merchant's LIVE inventory variation id    → the actual write target
```

**Canonical space is the sandbox catalog.** That is why the sandbox binding
([`data/bindings/sandbox_default_test_account_v1.json`](../data/bindings/sandbox_default_test_account_v1.json))
has empty `sold_variation_aliases` / `modifier_aliases` — the sandbox's own IDs
*are* the canonical IDs ("identity coverage"), so no translation is needed; only
`inventory_variation_ids` is populated.

Already-implemented supporting machinery:
- **Coverage / drift audit:**
  [`build_binding_coverage_report`](../app/binding_coverage_report.py)
  classifies, per merchant, *blocking* issues (aliases → non-existent canonical
  targets, aliases whose live source vanished, missing required inventory keys,
  stale inventory ids) vs *warnings* (`unmapped_live_variations`,
  `unmapped_live_modifiers`, `unknown_inventory_keys`), and computes
  `ready_for_approval = binding exists AND blocking_issue_count == 0`.
- **Lifecycle:** bindings are versioned with a draft → approve → activate flow
  (`upsert_catalog_binding`, `set_catalog_binding_status`,
  `get_active_catalog_binding`).
- **Environment scoping:** all merchant records are keyed by
  `environment#merchant_id[#location]`, so sandbox and production bindings
  coexist without collision.

## The actual gap

Not the mechanism, projection, coverage, or lifecycle — those are done. It is
exactly:

> For a **production merchant whose catalog IDs differ from canonical**,
> *generate* `sold_variation_aliases`, `modifier_aliases`, and
> `inventory_variation_ids` reliably and repeatably — instead of hand-authoring
> JSON like the sandbox file.

## Recommendation: a custom-attribute-driven binding builder

Derive the maps from **stable, catalog-resident tags**, never hand-author them.
A "binding builder" pulls the merchant's live catalog and emits a *draft*
binding, which then flows through the existing coverage + approval gate. The
join signal differs by object type — deliberately.

### Drinks → `mosa_recipe_key` (Dashboard-visible `SELECTION` custom attribute)

- Define once per merchant account via the Catalog API: `SELECTION` type, allowed
  values = the `drink_key`s, seller-visible, app-owned. `SELECTION` prevents
  typos; immutable schema makes it a stable join key.
- Operator tags each drink variation in the Dashboard (Edit Item → Variation →
  Custom attributes) — or bulk via CSV/API for the first pass.
- Builder: invert `recipe_map` once → `{ drink_key → canonical_variation_id }`,
  read each live variation's `mosa_recipe_key`, and emit
  `sold_variation_aliases[live_id] = canonical_id`. Untagged variations surface
  as `unmapped_live_variations` warnings — fail-safe, not silent.
- **Why custom attribute over name/SKU:** survives renames/repricing (the tag
  travels with the variation), app-namespaced (no collision with the merchant's
  own SKU usage), and `SELECTION` is typo-proof. SKU's only edge is bulk CSV
  import for a large first pass; name-matching is only good as a *suggester*.

### Inventory → `mosa_inventory_key` (symmetric `SELECTION` attribute)

The write side needs the same treatment: `inventory_variation_ids` must be
populated per merchant (the sandbox file hand-filled all of them). A second
`SELECTION` attribute (allowed values = `inventory_key`s) on the merchant's
inventory-tracking variations lets the builder emit
`inventory_variation_ids[inventory_key] = live_variation_id`. The coverage
report's `missing_required_keys` / `stale_live_variation_ids` already validate
completeness as **blocking**.

### Modifiers → name-matching seeder + operator confirmation (stored in the binding)

Custom attributes on `MODIFIER` exist but are **API-only — invisible in the
Dashboard** (`MODIFIER` since 2023-04-19, `MODIFIER_LIST` since 2024-04-17). That
removes the attribute's main advantage (UI tagging) *and* would write into the
merchant's catalog. So instead:

- Builder lists every live modifier and seeds suggestions by name ("100% Sugar",
  "Boba") — names are a hint, not the source of truth.
- Operator confirms/corrects the handful of suggestions once.
- Builder emits `modifier_aliases[live_id] = canonical_modifier_id` into the same
  binding; misses surface as `unmapped_live_modifiers` warnings.

This keeps the modifier mapping on **our** side, avoids mutating the merchant's
catalog, stays fail-closed, and is cheap because modifiers are a small fixed
vocabulary. (See also [`catalog-modifier-model.md`](catalog-modifier-model.md)
"Future direction" on collapsing many live IDs → one canonical modifier key.)

## Sandbox vs production: the overhead crossover

|  | Sandbox | Production |
|---|---|---|
| **Stimulus** (making an order exist) | **High** — no POS; orders are scripted (the canary) | **Zero** — real customers generate them |
| **Binding** (mapping catalog → canonical) | **Zero** — sandbox *is* canonical (identity coverage) | **High** — different IDs require aliases |

Sandbox is expensive to **exercise**; production is expensive to **map**. The two
do not overlap, and that is the design working in our favor: do the hard
*dynamic* validation where it is cheap and safe (sandbox), and require only a
cheap *static* check where dynamic testing is impossible (production).

## Validation strategy (what this implies)

You **cannot cheaply dynamic-test a production merchant's detection** before
go-live — no test cards, real money, no fabricated POS orders. The first real
customer order is the first live test. So validation splits into three
cleanly-separated jobs:

1. **Canary (sandbox, dynamic)** — validates the **engine**: canonical recipes,
   projection math, the webhook → SQS → worker pipeline. Runs against canonical
   IDs. It is *not* a per-merchant test. (`testing/run_live_cloud_canary`, the
   manual `smoke-canary.yml` workflow.)
2. **Coverage report (any env, static)** — validates a **specific merchant's
   binding** with no orders at all. **This is the production go-live gate**
   (`ready_for_approval`, `blocking_issue_count == 0`).
3. **Real production orders (post-launch, dynamic)** — the actual detection, with
   **fail-closed + alerting** as the safety net.

### Production go-live additions justified by the above

- **Tighter alerting than sandbox:** alert on blocked orders and on coverage
  warnings, so a missed mapping surfaces within minutes — not as silent inventory
  drift discovered weeks later.
- **A single deliberate "one real order" smoke at launch:** have the merchant
  ring up one real drink that we reconcile by hand. It is the production analog of
  the canary — not automated or repeatable, but it confirms the binding works
  against *their* live catalog once, which is otherwise untestable.

## Status: built vs. remaining

**Built & wired:** the binding `mapping` model, `canonicalize_order_summary`,
projection against canonical recipes, `resolve_inventory_variation_id`, the
coverage report, the versioned draft→approve→activate lifecycle, environment
scoping, the sandbox canary, and the manual smoke-canary workflow.

**Remaining (the work this doc scopes):**
1. The **binding builder** — catalog pull → read `mosa_recipe_key` /
   `mosa_inventory_key` + name-match modifiers → emit a draft binding → hand off
   to `build_binding_coverage_report`.
2. The two **custom-attribute definitions** (created at merchant connect time).
3. **Blocked-order + coverage-warning alerting** for production.
4. The **one-real-order launch smoke** procedure (runbook entry).

## Open decisions

- **Keep canonical = sandbox** (recommended; avoids re-keying `recipe_map.json`),
  vs. re-key recipes by `drink_key` (cleaner namespace, larger refactor).
- Whether to make `mosa_recipe_key` **seller-visible** (operator tags in
  Dashboard) or **seller-hidden** (app-only, tamper-proof).
- Bulk-onboarding path: SKU CSV first pass vs. attribute-only.
- Modifier canonicalization: keep ID-keyed, or collapse to canonical modifier
  keys per `catalog-modifier-model.md`.
