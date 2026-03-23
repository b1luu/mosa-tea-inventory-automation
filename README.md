## Context
This project is a small Sandbox-first backend experiment for learning how Square catalog webhooks, sold-out inspection, and dependency-driven availability might work for a tea menu.

The current design treats:
- item-level concepts as the business layer
- variation-level sold-out state as the Square operational layer

Right now the goal is not propagation yet. The goal is to reliably detect when a tracked Square variation changes and inspect its current sold-out state.

## Current Chain
```text
         Square Dashboard change
                    |
                    v
       `catalog.version.updated`
                    |
                    v
             webhook receive
                    |
                    v
             signature verify
                    |
                    v
           load local checkpoint
                    |
                    v
       search changed catalog objects
                    |
                    v
      filter tracked ITEM_VARIATIONs
                    |
                    v
   map variation IDs back to component keys
                    |
                    v
      retrieve full variation details
                    |
                    v
   inspect location_overrides[].sold_out
                    |
                    v
             update checkpoint
```

## Current Limitation
- Dependency propagation is not implemented yet.
- The component-to-variation mapping is still manually maintained.
- `catalog.version.updated` only tells us that the catalog changed, so follow-up Catalog API reads are still required to inspect current variation state.
- Square `sold_out` fields are read-only, so direct sold-out propagation inside Square is not available through the Catalog API.

## Future Plans
- Replace the current test mapping with real component keys such as `boba`, `brown_sugar_foam`, and `matcha_jelly`.
- Extend tracked object support beyond the current variation-based example.
- Explore modifier-based detection where dependencies are represented in Square as modifiers instead of variations.
- Continue treating the current webhook flow as a detection and inspection pipeline, not as direct Square sold-out propagation.
