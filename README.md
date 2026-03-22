## Context
This project is a small Sandbox-first backend experiment for learning how Square catalog webhooks, sold-out inspection, and dependency-driven availability might work for a tea menu.

The current design treats:
- item-level concepts as the business layer
- variation-level sold-out state as the Square operational layer

Right now the goal is not propagation yet. The goal is to reliably detect when a tracked Square variation changes and inspect its current sold-out state.

## Current Chain
1. A catalog change happens in Square Dashboard.
2. Square sends `catalog.version.updated` to the webhook endpoint.
3. The webhook signature is verified.
4. The app reads the last processed timestamp from a local state file.
5. The app searches Square for catalog objects changed since that timestamp.
6. The app filters changed objects down to tracked `ITEM_VARIATION` IDs using a local component-to-variation mapping.
7. The app retrieves the full variation object for those tracked matches.
8. The app inspects the current variation state, including `location_overrides[].sold_out`.
9. The app updates the local checkpoint after successful processing.

## Current Limitation
- Dependency propagation is not implemented yet.
- The component-to-variation mapping is still manually maintained.
- `catalog.version.updated` only tells us that the catalog changed, so follow-up Catalog API reads are still required to inspect current variation state.
