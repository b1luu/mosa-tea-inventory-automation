# Add new ingredient runbook

End-to-end procedure for adding a new tracked ingredient (with associated
drinks and/or modifiers) to a live production merchant's inventory system.

The canonical worked example is **SSR Oolong** + **Creme Brulee Powder**
added in PR #52. This doc generalizes that experience.

## When this runbook applies

- The boss adds a new tea base, syrup, topping, or any ingredient she
  wants to track.
- A new drink uses an existing ingredient but in a new way (e.g., new
  SSR Special with built-in Silky Custard topping).
- A new modifier (topping / cream foam / cheese cap) appears in the
  Square catalog.

For purely renaming an existing item (e.g., "Custard Powder" → "Creme
Brulee Powder"), see [`operator-recount-workflow.md`](operator-recount-workflow.md)
and the `annotate_backend_inventory_names` script — much smaller scope.

## Phase 1: Decisions before any code

Confirm with the merchant:

| Question | Why it matters |
|---|---|
| What does she **call** it? | Drives `name` in inventory_item_map, display name, Square dashboard label |
| What **stock unit** does she buy/track it in? | `bag` / `bottle` / `box` / `container` / `can` / `package` / `roll` / etc. |
| How big is one stock unit? | `stock_unit_size` (e.g., 600g per bag) + `stock_unit_size_unit` (`g` / `ml` / `cup` / `straw` / `lid`) |
| For a brewable tea: brew ratio? | `yield_conversion` — e.g., 100g dry → 4700ml brewed |
| Per-drink usage in each recipe that uses this ingredient | Drives `recipe_map.json` per-drink amounts |
| Is it part of a built-in topping (like Mist drinks) or only via modifier? | Determines whether to inline ingredients in the drink recipe OR add to `modifier_additions` |
| Current physical stock count | Initial seed value |

Don't skip these — guessing here means redoing work later. The boss's
recipe knowledge is the bottleneck, not the engineering.

## Phase 2: Code + data changes (one PR)

### 2.1 `data/inventory_item_map.json`

Add the new key. The schema for a tea base (with yield conversion):

```json
"ssr_oolong": {
  "square_variation_id": "MOSAEXT_INV_SSR_OOLONG_<random>",
  "name": "SSR Oolong",
  "unit": "g",
  "stock_unit": "package",
  "stock_unit_size": 600,
  "stock_unit_size_unit": "g",
  "category": "INV - Tea",
  "yield_conversion": {
    "input_amount": 100,
    "input_unit": "g",
    "output_amount": 4700,
    "output_unit": "ml"
  },
  "notes": "SSR Oolong (糯香烏龍). 1 package = 12 × 50g bags. Brew: 2 bags + 2800ml water + 1900g ice → 4700ml batch."
}
```

For a non-brewable ingredient (no yield_conversion):

```json
"creme_brulee_powder": {
  "square_variation_id": "MOSAEXT_INV_CUSTARD_POWDER_<random>",
  "name": "Creme Brulee Powder",
  "unit": "g",
  "stock_unit": "bag",
  "stock_unit_size": 1000,
  "stock_unit_size_unit": "g",
  "category": "INV - Powder",
  "notes": "1 batch of Silky Custard = 700ml water + 700g heavy cream + 280g this. Yields ~21 cups at 80g/scoop."
}
```

The `square_variation_id` uses the `MOSAEXT_` prefix as a sentinel —
clearly synthetic (matches existing entries we've added beyond the
canonical seed fixture).

### 2.2 `app/manual_count_sync.py` — `SUPPORTED_INVENTORY_KEYS`

Add the new key. Without this entry, the manual_count_sync Lambda rejects
recount values for the ingredient.

```python
SUPPORTED_INVENTORY_KEYS = {
    ...
    "ssr_oolong",            # NEW
    "creme_brulee_powder",   # NEW
}
```

### 2.3 `testing/fixtures/catalog/sandbox_canonical_catalog.json`

Add canonical fixture entries for:

1. The new inventory variation(s) — `sellable=false`, `stockable=true`
2. Any new sold-drink variations that use this ingredient
3. Any new modifier (e.g., Silky Custard cream cheese topping)

Use synthetic `MOSAEXT_*` ids consistently. The binding builder uses
these names to match against live merchant catalogs.

### 2.4 `data/recipe_map.json`

Three possible additions depending on the ingredient:

**A. Drinks that use this ingredient as a primary base**
Add a recipe entry per drink keyed by canonical sold_variation_id:

```json
"MOSAEXT_SSR_TEA_<random>": {
  "drink_key": "ssr_oolong_brewed_tea",
  "drink_name": "SSR Oolong Tea",
  "ingredients": [
    {
      "inventory_key": "ssr_oolong",
      "amount": 300,
      "unit": "ml",
      "notes": "Brewed SSR Oolong volume per drink."
    }
  ]
}
```

**B. Hot variants — use `same_as`**

```json
"MOSAEXT_SSR_HOT_TEA_<random>": {
  "same_as_sold_variation_id": "MOSAEXT_SSR_TEA_<random>"
}
```

Also append the hot variation's id to
`default_packaging_config.hot_sold_variation_ids` so it gets `hot_cup`
and `hot_lid` instead of cold packaging.

**C. New modifier additions**

```json
"modifier_additions": {
  "MOSAEXT_MOD_SILKY_CUSTARD_<random>": {
    "ingredients": [
      { "inventory_key": "heavy_cream",         "amount": 33.33, "unit": "g", "notes": "..." },
      { "inventory_key": "creme_brulee_powder", "amount": 13.33, "unit": "g", "notes": "..." }
    ]
  }
}
```

**D. Built-in topping (Mist pattern)**

If a drink ALWAYS includes a topping by design (not customer-selected),
inline the ingredients in the drink recipe AND add the drink_key to a
list like `default_packaging_config.recipes_with_built_in_cream_foam`
(for the cold cup lid logic). See PR #51 for the Mist drinks reference.

### 2.5 Tests

`testing/test_order_inventory_projection.py` — add tests verifying the
new drinks/modifiers deduct correctly. Use `project_line_item_usage`
directly with the new canonical ids.

Pattern (from the SSR PR):

```python
def test_ssr_oolong_tea_deducts_brewed_leaves_only(self):
    recipes = load_recipe_map()
    ssr_tea_id = next(
        cid for cid, r in recipes["sold_variation_recipes"].items()
        if r.get("drink_key") == "ssr_oolong_brewed_tea"
    )
    no_sugar = "IDFKCCIPYGFA67OPJMJ3SQVO"
    projected = project_line_item_usage(ssr_tea_id, "1", [no_sugar])
    combined = {u["inventory_key"]: u["total_amount"] for u in projected["usage"]}
    self.assertAlmostEqual(combined["ssr_oolong"], 100 * 300 / 4700)
```

Run `./.venv/bin/python -m unittest discover -s testing -p 'test_*.py'`
— full suite must pass.

### 2.6 `testing/fixtures/catalog/simulated_production_catalog.json`

If you added inventory variations to the canonical fixture, also add
corresponding simulated entries so the existing binding-coverage
integration test still passes:

```json
"PRODSIM-V-SSR-OOLONG": {
  "id": "PRODSIM-V-SSR-OOLONG",
  "item_name": "SSR Oolong",
  "sellable": false,
  "stockable": true,
  "variation_name": "Regular"
}
```

## Phase 3: Production rollout (after the PR is merged)

These steps mutate real Mosa Tea catalog state. Run them in order.

### 3.1 Create the backend inventory item(s) in Mosa Tea's Square catalog

```bash
DYNAMODB_MERCHANT_CONNECTION_TABLE=mosa-tea-merchant-connections-prod \
MERCHANT_SECRET_PREFIX=mosa-tea-prod/merchant-auth \
./.venv/bin/python -m scripts.create_backend_inventory \
  --merchant MLXZ38BC27GAD --environment production --apply
```

> ⚠️ **Known bug** as of 2026-06: this script uses **name-match** to detect
> existing items. After `annotate_backend_inventory_names` has renamed items
> to include unit annotations (e.g., "TGY (bag, 600g)"), the script no
> longer recognizes them as existing and tries to create duplicates. If
> you see `to create: N | skipped: <small>` where N > the count of truly
> new items, **STOP** before the `--apply` completes.
>
> Workaround until the fix lands: temporarily edit the script's
> `_active_item_names()` to ALSO accept items whose `inventory_key` is
> already in `data/backend_inventory_created_ids.json`. Or just run the
> create against a fresh merchant.

### 3.2 Organize + annotate the new items

```bash
DYNAMODB_MERCHANT_CONNECTION_TABLE=mosa-tea-merchant-connections-prod \
MERCHANT_SECRET_PREFIX=mosa-tea-prod/merchant-auth \
./.venv/bin/python -m scripts.organize_backend_inventory \
  --merchant MLXZ38BC27GAD --environment production --apply
```

```bash
DYNAMODB_MERCHANT_CONNECTION_TABLE=mosa-tea-merchant-connections-prod \
MERCHANT_SECRET_PREFIX=mosa-tea-prod/merchant-auth \
./.venv/bin/python -m scripts.annotate_backend_inventory_names \
  --merchant MLXZ38BC27GAD --environment production --apply
```

Both are idempotent — already-organized / already-annotated items are
no-ops.

### 3.3 Rebuild the merchant binding

```bash
DYNAMODB_MERCHANT_CONNECTION_TABLE=mosa-tea-merchant-connections-prod \
DYNAMODB_MERCHANT_CATALOG_BINDING_TABLE=mosa-tea-merchant-bindings-prod \
MERCHANT_SECRET_PREFIX=mosa-tea-prod/merchant-auth \
./.venv/bin/python -m scripts.build_merchant_binding \
  --environment production --merchant-id MLXZ38BC27GAD \
  --output-file data/bindings/draft_mosa_tea_prod_v<N>.json
```

> Expected gotcha: the rebuild's `inventory_variation_ids` will be empty
> (annotated names break the binding-builder's name-match for inventory
> items). **Patch** the draft by overlaying
> `data/backend_inventory_created_ids.json` on top of
> `inventory_variation_ids` before upserting.
>
> Also: the rebuild starts with empty `ignored_live_variation_ids` —
> preserve the previous version's list, removing any items that are now
> mapped via this PR.

### 3.4 Upsert + approve the new binding version

```bash
./.venv/bin/python -m scripts.upsert_merchant_catalog_binding \
  --environment production --merchant-id MLXZ38BC27GAD \
  --location-id LZ4JV6WQHPQVE --version <N> \
  --mapping-file data/bindings/draft_mosa_tea_prod_v<N>.json \
  --notes "v<N> + <ingredient/drink summary>"
```

```bash
./.venv/bin/python -m scripts.approve_merchant_catalog_binding \
  --environment production --merchant-id MLXZ38BC27GAD \
  --location-id LZ4JV6WQHPQVE --version <N>
```

### 3.5 Seed initial stock counts

Via Square dashboard (for 1–2 items, easier UI), OR via the seed script
(for many items at once):

**Dashboard path** (recommended for 1–2 new items):
- Items & services → Item library → Backend Inventory filter
- Click the new item → variation → Stock action → **Physical count**
  (or Stock received if going 0 → N)
- Enter the count → Save

**Script path** — create a minimal JSON file with just the new items:

```bash
cat > /tmp/new-items-seed.json <<JSON
{
  "ssr_oolong": 20,
  "creme_brulee_powder": 40
}
JSON

OPERATOR_API_TOKEN='<prod-token>' \
./.venv/bin/python -m scripts.seed_inventory_counts \
  --counts-file /tmp/new-items-seed.json \
  --merchant-id MLXZ38BC27GAD --location-id LZ4JV6WQHPQVE \
  --environment production \
  --api-url https://60ohinmt7k.execute-api.us-west-2.amazonaws.com \
  --source-reference new-item-seed-<date> --apply
```

> ⚠️ **Do NOT re-apply the full `data/initial_stock_counts.json`** — that
> file represents the original seed values; re-applying overwrites all
> the deduction history accumulated since go-live. Use a one-shot JSON
> with ONLY the new items.

### 3.6 Update the Apps Script

In the Apps Script editor for the boss's Google Sheet:

1. Add the new inventory_key to `COUNTED_UNIT_BY_KEY` with the right
   counted_unit:

   ```javascript
   const COUNTED_UNIT_BY_KEY = {
     ...
     ssr_oolong:          "package",   // NEW
     creme_brulee_powder: "bag",       // NEW
   };
   ```

2. In the Sheet itself, add a row for the new ingredient and fill in
   column C with the snake_case `inventory_key`. If the new row goes
   beyond `END_ROW` (currently 42), bump `END_ROW` in the script.

### 3.7 End-to-end verification

Place a real customer order containing a drink that uses the new
ingredient. Watch the worker logs:

```bash
aws logs tail /aws/lambda/mosa-tea-webhook-worker-prod --region us-west-2 --follow
```

Then snapshot the affected inventory keys:

```bash
DYNAMODB_MERCHANT_CONNECTION_TABLE=mosa-tea-merchant-connections-prod \
DYNAMODB_MERCHANT_CATALOG_BINDING_TABLE=mosa-tea-merchant-bindings-prod \
MERCHANT_SECRET_PREFIX=mosa-tea-prod/merchant-auth \
./.venv/bin/python -m scripts.inventory_snapshot \
  --merchant MLXZ38BC27GAD --environment production \
  --location-id LZ4JV6WQHPQVE
```

The new ingredient should show a small fractional deduction matching the
recipe (e.g., one SSR Tea = 0.01064 packages of ssr_oolong).

## Gotchas summary

| Risk | Mitigation |
|---|---|
| `create_backend_inventory` creates duplicates after items are annotated | Eyeball the dry-run before `--apply`; expect `to_create == count_of_new_items` |
| Binding rebuild loses inventory_variation_ids | Overlay from `backend_inventory_created_ids.json` before upserting |
| Binding rebuild empties `ignored_live_variation_ids` | Preserve from previous active version, minus any items now mapped |
| Forgetting to add new key to `SUPPORTED_INVENTORY_KEYS` | Lambda rejects manual sync requests for that key |
| Forgetting to update Apps Script `COUNTED_UNIT_BY_KEY` | Sheet sync silently skips that row with a prep error |
| Forgetting the simulated fixture entry for new inventory items | `test_simulated_catalog_yields_approvable_binding` fails |
| Applying the full initial_stock_counts.json again to seed new items | Wipes all order-driven deduction history |

Read these once before starting; one of them will bite you each time.

## When to NOT add a new ingredient

If the new ingredient is intentionally untracked (e.g., the boss uses an
infinite-supply seal film roll, or doesn't want to track water), DON'T
add it to `inventory_item_map.json`. Recipe entries can omit it. The
worker silently produces no deduction for unknown inventory keys.

For ingredients added to inventory_item_map but **deliberately not
synced** (e.g., milk, heavy_cream, frozen fruits), see the "5 unsupported
keys" note in [`operator-recount-workflow.md`](operator-recount-workflow.md).
The worker deducts them on orders (using the recipe), but they can't be
seeded or recounted via the manual sync endpoint until added to
`SUPPORTED_INVENTORY_KEYS`. The boss must set their counts via Square
dashboard directly.
