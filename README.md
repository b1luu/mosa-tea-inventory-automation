## Context
This project is a Sandbox-first inventory intelligence system for a drink menu built on Square.

The current goal is:
- map sold drink variation IDs to recipe usage
- convert recipe usage into inventory depletion
- project ingredient, topping, foam, sweetener, fruit, and packaging usage from completed orders
- apply Sandbox inventory adjustments to internal stock-tracked supply items
- model inventory in human-readable stock units such as bags, cartons, bottles, boxes, and containers

This is no longer centered on Square `sold_out` propagation.

## Current Flow
```text
      completed Square order
                |
                v
        retrieve order by ID
                |
                v
   inspect line items + modifiers
                |
                v
      resolve recipe_map.json
                |
                v
 expand tea bases / overrides / modifiers
                |
                v
 convert recipe units into inventory units
                |
                v
      combine usage by inventory item
                |
                v
 summarize into stock / SKU display units
                |
                v
   build Inventory API adjustments
                |
                v
 apply IN_STOCK -> WASTE in Sandbox
```

## Proven So Far
- Completed orders can be retrieved and inspected reliably with the Orders API.
- Sold drink variation IDs can be mapped to recipes in `data/recipe_map.json`.
- Internal supply items in Square Item Library can act as the inventory ledger.
- Brew-yield conversions in `data/inventory_item_map.json` convert brewed tea and matcha usage into dry inventory decrements.
- Recipe projection now covers:
  - brewed teas
  - milk teas
  - au lait drinks
  - matcha drinks
  - fruit drinks
  - additive toppings
  - built-in toppings
  - batch-derived toppings
  - cream foam modifiers
  - sugar-level scaling
  - packaging items
- Stock/SKU unit metadata is modeled for all current inventory items.
- Sandbox inventory adjustments now work through the Inventory API using positive quantities and `IN_STOCK -> WASTE`.
- SQLite-backed order-processing state prevents accidental reprocessing of the same completed order.
- Local fixture tests and controlled live Sandbox flows both work.

## Project Structure
- `data/recipe_map.json`
  - sold variation to recipe mapping
  - tea base definitions
  - modifier-driven additions
  - sugar-level multiplier map
  - default packaging config
- `data/inventory_item_map.json`
  - internal supply variation IDs
  - yield conversions
  - stock / SKU unit metadata
- `app/order_inventory_projection.py`
  - recipe resolution and inventory projection
- `app/processed_orders_state.py`
  - compatibility layer over the SQLite order-processing ledger
- `app/order_processing_db.py`
  - SQLite-backed order-processing state helpers
- `app/inventory_stock_units.py`
  - display conversion from inventory units into stock / SKU units
- `scripts/search_orders.py`
  - search recent Square orders
- `scripts/inspect_order.py`
  - inspect one order's shape
- `scripts/apply_inventory_adjustments.py`
  - dry-run or apply inventory adjustments
- `testing/create_live_test_order.py`
  - create and optionally pay a live Sandbox order from a named scenario
- `testing/run_live_inventory_flow.py`
  - create, pay, and run a full dry-run or apply flow end to end
- `testing/test_order_inventory_projection.py`
  - local fixture-based projection tests

## Running It
- Search recent completed orders:
  - `./.venv/bin/python -m scripts.search_orders`
- Inspect a specific order:
  - `./.venv/bin/python -m scripts.inspect_order ORDER_ID`
- Dry-run inventory adjustments for a trusted completed order:
  - `./.venv/bin/python -m scripts.apply_inventory_adjustments ORDER_ID`
- Apply Sandbox inventory adjustments:
  - `./.venv/bin/python -m scripts.apply_inventory_adjustments --apply ORDER_ID`
- Run fixture-based projection tests:
  - `./.venv/bin/python -m unittest testing.test_order_inventory_projection`
- Run controlled live Sandbox flow:
  - `./.venv/bin/python -m testing.run_live_inventory_flow SCENARIO`
- Run controlled live Sandbox flow and apply inventory:
  - `./.venv/bin/python -m testing.run_live_inventory_flow --apply SCENARIO`

## Inventory Model
- Recipe logic works in physical units such as `ml`, `g`, `cup`, `straw`, and `lid`.
- Square inventory can still be displayed in operational stock units such as:
  - `bag`
  - `box`
  - `bottle`
  - `carton`
  - `container`
- The projection pipeline supports:
  - direct recipe ingredients
  - modifier-selected recipe branches
  - fixed additive modifiers
  - batch-derived modifiers
  - sugar-level scaling
  - default packaging rules
  - conditional packaging rules

## Menu Coverage
- Current coverage includes cold drinks and current Sandbox packaging assumptions.
- Covered ingredient families include:
  - tea leaves and brewed tea bases
  - matcha
  - milk
  - non-dairy creamer
  - sugar syrup and sweeteners
  - fruit syrups
  - frozen fruit
  - toppings such as boba, lychee jelly, tea jelly, and Hun Kue
  - cream foam modifiers
  - cups, straws, and cold cup lids
- Hot-drink packaging is not modeled yet.

## Testing
- The local test suite uses fixture orders under `testing/fixtures/orders`.
- The live Sandbox test flow creates real orders, pays them, and then runs the projection or apply pipeline.
- Dry-run mode in the live flow still creates and pays a real Sandbox order; it only skips the inventory apply step.

## Notes On Inventory Adjustments
- The working adjustment model is:
  - positive quantity
  - `from_state: "IN_STOCK"`
  - `to_state: "WASTE"`
- Using negative quantities for adjustments is invalid in Square.
- Internal ingredient items are treated as consumed stock, not directly sold catalog items.

## Processing States
- `pending`
  - a completed Square order has entered the processing workflow, but inventory has not been successfully adjusted yet
- `blocked`
  - a completed order should not be auto-applied because projection was incomplete or unsafe
- `failed`
  - a completed order was attempted, but processing or inventory apply failed
- `applied`
  - the inventory adjustment succeeded

Square order state and app processing state are separate concepts. The app only processes inventory for Square orders that are already `COMPLETED`.

## Current Limitations
- The mapping files are Sandbox-only right now.
- Some older Sandbox orders are noisy or unrealistic, so controlled live scenarios are often a better test input than historical order data.
- Webhook infrastructure exists, but the main proven workflow is still controlled-run processing rather than fully automated production ingestion.
- Packaging is currently modeled with a cold-drink default:
  - `u600_cup`
  - conditional straw selection
  - conditional cold cup lids for cream foam
- Hot drinks and hot-drink packaging are intentionally out of scope right now.

## Next Steps
- Add hot-drink packaging and container rules.
- Expand live scenario coverage for more menu combinations.
- Harden automation around retries, replay, and webhook-driven processing.
- Split Sandbox and Production mappings cleanly when Production access is ready.
