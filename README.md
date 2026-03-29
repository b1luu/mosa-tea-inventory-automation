# Mosa Tea Inventory Automation

This project was built for Mosa Tea as part of an internship and models a Sandbox-first inventory intelligence system for a drink menu built on Square.

The current goal is:
- map sold drink variation IDs to recipe usage
- convert recipe usage into inventory depletion
- project ingredient, topping, foam, sweetener, fruit, and packaging usage from completed orders
- apply Sandbox inventory adjustments to internal stock-tracked supply items
- model inventory in human-readable stock units such as bags, cartons, bottles, boxes, and containers

This is no longer centered on Square `sold_out` propagation.

## Environment
Create a local `.env` file from `.env.example` and fill in your own Square Sandbox credentials and webhook values.

Required variables:
- `SQUARE_ACCESS_TOKEN`
- `SQUARE_ENVIRONMENT`
- `SQUARE_WEBHOOK_SIGNATURE_KEY`
- `SQUARE_WEBHOOK_NOTIFICATION_URL`

## Current Flow
```text
     completed Square order webhook
                |
                v
   webhook verification + order gating
                |
                v
   SQLite processing state entry created
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
                |
                v
   SQLite state ends at applied / blocked / failed
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
- Order webhook automation now works end to end for completed orders.
- A lightweight admin console exists for monitoring and replaying order-processing states.
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
- `app/order_processor.py`
  - shared processing pipeline used by both webhook and CLI entrypoints
- `app/admin_routes.py`
  - lightweight admin and replay routes
- `app/inventory_stock_units.py`
  - display conversion from inventory units into stock / SKU units
- `scripts/search_orders.py`
  - search recent Square orders
- `scripts/inspect_order.py`
  - inspect one order's shape
- `scripts/apply_inventory_adjustments.py`
  - thin CLI wrapper around the shared processor
- `scripts/list_order_processing_states.py`
  - inspect the SQLite processing ledger
- `scripts/replay_order.py`
  - replay one specific order through the processor
- `scripts/replay_failed_orders.py`
  - bulk replay failed orders
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
- Run the local webhook/admin server:
  - `uvicorn server:app --reload --port 8000`
- View the admin console:
  - `http://127.0.0.1:8000/admin/order-processing`
- Inspect the SQLite processing ledger:
  - `./.venv/bin/python -m scripts.list_order_processing_states`
- Replay one order:
  - `./.venv/bin/python -m scripts.replay_order ORDER_ID`
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
- Current coverage includes cold drinks, hot drinks, and current Sandbox packaging assumptions.
- Covered ingredient families include:
  - tea leaves and brewed tea bases
  - matcha
  - milk
  - non-dairy creamer
  - sugar syrup and sweeteners
  - fruit syrups
  - frozen fruit
  - toppings such as boba, lychee jelly, tea jelly, and Hun Kue
  - matcha jelly
  - cream foam modifiers
  - cups, straws, cold cup lids, hot cups, and hot lids

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
- The system is still optimized for local/internal operation rather than hosted production deployment.
- The admin console is intentionally lightweight and currently has no authentication layer; do not expose it publicly as-is.
- Packaging rules are modeled for the current menu, but future menu expansion will likely require more packaging/config variants.
- Operational alerting and reconciliation are not implemented yet.

## Next Steps
- Add monitoring and alerting for failed or blocked orders.
- Expand live scenario coverage for more menu combinations.
- Harden the processing ledger with richer error and attempt metadata.
- Split Sandbox and Production mappings cleanly when Production access is ready.
