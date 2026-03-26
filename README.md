## Context
This project is a Sandbox-first inventory intelligence prototype for a tea menu built on Square.

The current goal is:
- map sold drink variation IDs to recipe usage
- convert brewed-tea volumes into dry inventory consumption
- project ingredient usage from completed orders
- apply Sandbox inventory adjustments to internal stock-tracked supply items

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
    expand tea bases / overrides
                |
                v
 convert ml usage into inventory grams
                |
                v
      combine usage by inventory item
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
- Brew-yield conversions in `data/inventory_item_map.json` can convert drink usage into dry inventory decrements.
- Batch projection across completed orders works.
- Sandbox inventory adjustments now work through the Inventory API using positive quantities and `IN_STOCK -> WASTE`.
- Local processed-order tracking prevents accidental reprocessing of the same completed order.

## Project Structure
- `data/recipe_map.json`
  - sold variation to recipe mapping
  - tea base definitions
  - modifier-aware overrides for configurable drinks
- `data/inventory_item_map.json`
  - internal supply variation IDs
  - yield conversions
- `app/order_inventory_projection.py`
  - recipe resolution and inventory projection
- `app/processed_orders_state.py`
  - local idempotency ledger
- `scripts/search_orders.py`
  - search recent completed orders
- `scripts/inspect_order.py`
  - inspect one order's shape
- `scripts/apply_inventory_adjustments.py`
  - dry-run or apply inventory adjustments

## Running It
- Search recent completed orders:
  - `./.venv/bin/python -m scripts.search_orders`
- Inspect a specific order:
  - `./.venv/bin/python -m scripts.inspect_order ORDER_ID`
- Dry-run inventory adjustments for a trusted completed order:
  - `./.venv/bin/python -m scripts.apply_inventory_adjustments ORDER_ID`
- Apply Sandbox inventory adjustments:
  - `./.venv/bin/python -m scripts.apply_inventory_adjustments --apply ORDER_ID`

## Current Limitations
- The mapping files are Sandbox-only right now.
- Some older Sandbox orders are noisy or unrealistic, so hand-picked completed orders are the safest test input.
- Modifier-dependent drinks only work when the relevant modifier IDs are present on the order.
- The local processed-order ledger prevents duplicate processing inside this app, but historical Sandbox tests can still contain earlier accidental duplicate adjustments.
- Non-tea ingredients are not the focus yet; the current model is mainly proving tea-base inventory logic.

## Notes On Inventory Adjustments
- The working adjustment model is:
  - positive quantity
  - `from_state: "IN_STOCK"`
  - `to_state: "WASTE"`
- Using negative quantities for adjustments is invalid in Square.
- Internal ingredient items are treated as consumed stock, not directly sold catalog items.

## Next Steps
- Add a trusted-date-window search flow so recent completed orders can be processed without hand-picking every order ID.
- Continue refining modifier-aware recipes where tea base choice changes ingredient usage.
- Decide whether to add non-tea ingredient consumption after the tea-base proof of concept.
- Later, when Production access exists, split Sandbox and Production mappings cleanly.
