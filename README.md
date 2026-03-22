## Current Chain
1. Manual sold-out toggle in Square Dashboard
2. `catalog.version.updated` webhook arrives
3. Webhook signature is verified
4. `last_synced_at` is read from `data/catalog_sync_state.json`
5. `SearchCatalogObjects` runs with `begin_time=last_synced_at`
6. Changed catalog objects are printed
7. Changed `ITEM_VARIATION` objects are matched against `data/component_variation_map.json`
8. Matching variation IDs are reverse-mapped back to component keys
9. `RetrieveCatalogObject` loads the full variation details
10. Current sold-out-related fields are printed from `location_overrides`
11. Checkpoint is updated after successful processing

## Current Files
Core app logic:
- `app/config.py`
- `app/client.py`
- `app/catalog_change_search.py`
- `app/catalog_sync_state.py`
- `app/component_variation_map.py`
- `app/catalog_custom_attributes.py`
- `app/catalog_lookup.py`

CLI / scripts:
- `scripts/setup_required_components.py`
- `scripts/explore_catalog.py`

Webhook server:
- `server.py`

Local runtime data:
- `data/catalog_sync_state.json`
- `data/component_variation_map.json`

## Current Data Files
`data/catalog_sync_state.json`
- Stores the last processed catalog timestamp.

`data/component_variation_map.json`
- Stores the business-facing component key to Square variation ID mapping.
- The server builds the reverse `variation_id -> component_key` map in memory at runtime.

## Current Limitation
- Dependency propagation is not implemented yet.
- The component mapping file is still manually maintained.
- The current tracked example uses:
  - `genmai_green_milk_tea -> MFEUN6CYRHERVYYWV7H7WWVZ`
- `catalog.version.updated` only tells us that the catalog changed, so the app still needs follow-up Catalog API reads to inspect current variation state.
