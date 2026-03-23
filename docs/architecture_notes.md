# Architecture Notes

## Current Status

The current system can:
- receive `catalog.version.updated` webhooks from Square Sandbox
- verify the Square webhook signature
- read a local checkpoint from `data/catalog_sync_state.json`
- search for changed catalog objects since the last checkpoint
- filter changed objects to tracked `ITEM_VARIATION` IDs
- map tracked variation IDs back to logical keys using `data/component_variation_map.json`
- retrieve the full variation object and inspect `location_overrides[].sold_out`

This validates the full webhook -> search -> inspect pipeline for a tracked variation.

## Important Square Constraint

Square lets us inspect sold-out state, but not programmatically set it through the Catalog API.

Read-only fields discovered:
- `ItemVariationLocationOverrides.sold_out`
- `ModifierLocationOverrides.sold_out`

Implication:
- direct sold-out propagation inside Square is not available through the `sold_out` field
- we can detect and reason about sold-out state, but we cannot rely on writing `sold_out` back to dependent drinks or modifiers

## Current Mapping Direction

For MVP, the tracked-object mapping moved from a hardcoded variation ID in code to a local JSON file:

- `data/component_variation_map.json`

Current shape:

```json
{
  "component_variation_map": {
    "genmai_green_milk_tea": "MFEUN6CYRHERVYYWV7H7WWVZ"
  }
}
```

The app loads:
- `component_key -> variation_id`

Then builds in memory:
- `variation_id -> component_key`

This is better than hardcoding because the tracking logic is now data-driven instead of code-driven.

## Modifier vs Variation Reality

Important distinction:
- item and availability inspection work at the `ITEM_VARIATION` level
- modifiers are separate catalog objects and do not use variation IDs

If a dependency is represented as a Square modifier, then dependency detection may need a modifier-based mapping instead of a variation-based mapping.

## Current Product Direction

A stronger long-term direction emerged during the design discussion:

- use Square webhooks and catalog inspection as operational signals
- build ingredient intelligence outside of Square's read-only sold-out model

Example idea:
- SKU layer: black tea bag, milk, boba, foam ingredients
- batch yield layer: 140g black tea -> 6000 ml brewed tea
- drink recipe layer: Taiwanese Retro consumes 200 ml black tea at 100% ice

This points toward an internal availability engine that computes drink availability from:
- ingredient SKUs
- prep yields
- recipe consumption

## Possible Operational Compromise

One possible workaround discussed:
- staff manually marks a modifier like `boba` sold out in POS/Dashboard
- the app detects that signal
- the app updates an inventory-tracked item variation through the Inventory API

This may be useful operationally, but it is still a workaround and needs careful thinking around:
- what object should hold the inventory truth
- how back-in-stock restoration should work
- whether drink inventory counts are being used as real stock or just as availability controls

## Open Questions

1. Should dependencies ultimately be modeled from modifiers, hidden item variations, or a mix of both?
2. Should the next mapping file be component-to-variation only, or expand to component-to-object-type/object-id?
3. Should the next milestone focus on:
   - modifier sold-out detection only
   - internal ingredient intelligence schema
   - Inventory API experiments
4. What is the clean restoration rule when something returns from sold out to back in stock?
