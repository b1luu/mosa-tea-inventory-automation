# Backend Inventory Organization (archive + single category)

> **Decision (chosen).** Keep Square as the inventory store, but make the
> stock-tracked "backend" items **invisible and contained**: move all of them
> into one **"Backend Inventory"** category and **archive** them. They vanish
> from the active item library and the sellable menu, while their counts stay
> live and API-writable. No custom dashboard to build; viewable on demand in
> Square itself.

## Why this works (proven in sandbox)

- **You can write inventory to archived items.** Verified via probe: created a
  tracked item, archived it, wrote a physical count through
  `inventory.batch_create_changes` (the *same* call the worker uses), read back
  the new value. Archiving hides an item; it does not freeze its stock.
- **Reads/writes are by variation ID, not by listing the catalog.** The worker
  and the canary resolve inventory targets from
  `data/inventory_item_map.json` and call `batch_get_counts` /
  `batch_create_changes` by `catalog_object_id`
  ([inspect_inventory_count.py:107](../scripts/inspect_inventory_count.py#L107)).
  Archiving therefore does **not** affect the runtime pipeline or the canary.

## The one consequence to know: `catalog.list` excludes archived items

`catalog.list` is **eventually consistent** and ultimately **omits archived
items** (confirmed: an item archived earlier no longer appears; freshly archived
ones linger briefly with `is_archived=true`, then drop). So anything that
*lists* the catalog stops seeing these items.

- **Unaffected:** the worker, the canary, and the demo (the demo uses committed
  catalog fixtures).
- **Affected (follow-up before production onboarding):** the binding
  **coverage report** and the production **binding builder** load a catalog
  snapshot via `catalog.list`
  ([binding_coverage_report.py:110](../app/binding_coverage_report.py#L110)).
  Once inventory items are archived, those tools would flag the
  `inventory_variation_ids` as stale/missing.
  - **Fix (done for the coverage report):** `build_binding_coverage_report` now
    backfills any binding-referenced id missing from the list via `batch_get`
    (which returns archived objects), so archived inventory items are validated
    **by ID** and never false-flagged as stale. The production binding builder's
    live-catalog loader should reuse the same pattern when it's wired to a live
    catalog (it currently runs pre-archive, so it sees the items anyway).

## The tool

`scripts/organize_backend_inventory.py` — account-agnostic (runs against
whatever `SQUARE_ENVIRONMENT`/token is configured), idempotent, reversible.

```
# preview (no changes):
./.venv/bin/python -m scripts.organize_backend_inventory
# apply (writes a backup first):
./.venv/bin/python -m scripts.organize_backend_inventory --apply
# revert from the backup:
./.venv/bin/python -m scripts.organize_backend_inventory --revert <backup.json>
```

- Targets exactly the items backing `data/inventory_item_map.json` (resolved to
  their parent items) — 38 items in sandbox, no drinks.
- Edits **in place** (preserves item/variation IDs and versions) — so the recipe
  binding and canary are undisturbed. Never deletes/recreates.
- Writes a timestamped backup to `data/backend_inventory_backups/` before
  applying; `--revert` restores prior `is_archived` + category for every item.

## Permissions

- **Catalog write is required** to archive/recategorize. In **sandbox** the
  full-access token already allows it. In **production**, the OAuth token needs
  **`ITEMS_WRITE`** — adding it requires the merchant to **re-authorize** once.
- Scope boundary for non-technical stakeholders: `ITEMS_WRITE` = *edit the
  menu/catalog* (used here only for the one-time organizing — archiving +
  categorizing backend items). It is **not** payments and **not** orders. The
  per-sale stock deductions use `INVENTORY_WRITE` (separate, already required).

## Production translation (the plan)

Production has **no backend inventory items yet** (its catalog is drinks/merch
only), so unlike sandbox it needs a *creation* step — and the **ordering
matters**: you must capture the inventory IDs while items are still listable,
**before** archiving.

1. Grant **`ITEMS_WRITE`** on the production OAuth app; merchant re-authorizes.
   (No personal access token is available in production, so the one-time catalog
   writes go through the OAuth token.)
2. **Create the backend inventory items + capture IDs** (create-and-capture):
   create the ~38 stock items in production and record each returned variation id
   straight into the binding's `inventory_variation_ids`. Because you create
   them, you *own* the ids directly — no name-matching needed for the inventory
   side. *(Tool not yet built; the production inventory-side counterpart to the
   organize/builder tools.)*
3. **Build the rest of the binding** with the read-only builder — name-match the
   **sold drinks** (which already exist in production) → `sold_variation_aliases`
   + `modifier_aliases`.
4. **Then** run `organize_backend_inventory --apply` against production to
   archive + categorize the backend items (backs up first, reversible).
5. **#2 (done)** keeps the coverage report honest against the now-archived
   catalog.
6. Confirm in the production Dashboard: backend items absent from the active
   library, present under the Archived filter, counts visible in Reports →
   Inventory.
7. Run the smoke canary to confirm the pipeline still deducts end-to-end (it
   operates by ID, so it should be green).

## Viewing inventory on demand

Counts live in Square, so no custom UI is needed:
- **Dashboard → Items → Item library → Status = Archived** (optionally filter to
  the Backend Inventory category) — see the items; check whether the Stock
  column renders for archived items.
- **Dashboard → Reports → Inventory/Stock** — counts show regardless of archive
  state.
