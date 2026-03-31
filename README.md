# Mosa Tea Inventory Automation

Built for Mosa Tea during an internship, this project turns completed Square drink orders into ingredient and packaging inventory depletion.

It sits between Square Orders and Square Inventory and answers a practical operations problem: a POS can tell you what was sold, but not what raw materials and packaging were actually consumed.

## Why This Exists

Drink menus are not one-to-one with inventory.

A single sold item can imply:
- brewed tea usage derived from dry leaves
- modifier-driven add-ons like boba or lychee jelly
- batch-derived components like tea jelly, Hun Kue, and cream foams
- sugar-level scaling
- packaging consumption such as cups, lids, and straws

This project models that gap and automates the translation from a completed order into inventory adjustments.

## What It Does

- Receives Square order webhooks
- Verifies webhook signatures
- Gates processing to completed orders
- Resolves sold drink variation IDs into recipe definitions
- Expands toppings, foam modifiers, built-in inclusions, and sugar rules
- Converts recipe units into inventory units and then stock/SKU units
- Applies Square Inventory adjustments against internal supply items
- Tracks processing state in SQLite
- Exposes a lightweight admin console for monitoring and replay

## Architecture

```text
                   Square Sandbox
          +-------------------------------+
          | Orders API | Inventory API    |
          | Webhooks   | Catalog / Items  |
          +-------------------------------+
                    |            ^
                    v            |
          POST /webhook/square   |
                    |            |
                    v            |
         +---------------------------+
         | FastAPI server            |
         | server.py                 |
         | - webhook verification    |
         | - order gating            |
         | - admin routes + static   |
         +---------------------------+
                    |
                    v
         +---------------------------+
         | Shared processing layer   |
         | app/order_processor.py    |
         | - fetch orders            |
         | - project usage           |
         | - build inventory writes  |
         | - transition DB state     |
         +---------------------------+
              |               |
              v               v
   +------------------+   +----------------------+
   | Recipe + item    |   | SQLite order ledger  |
   | config JSON      |   | data/order_processing|
   | data/*.json      |   | .db                  |
   +------------------+   +----------------------+
              |
              v
   +-----------------------------+
   | Inventory projections       |
   | - ingredients               |
   | - toppings                  |
   | - foam                      |
   | - packaging                 |
   +-----------------------------+
              |
              v
   +-----------------------------+
   | Square inventory adjustment |
   | IN_STOCK -> WASTE           |
   +-----------------------------+
```

## Webhook / Event Flow

```text
Square sends order.created / order.updated
                |
                v
FastAPI verifies signature
                |
                v
Ignore non-completed orders
                |
                v
If COMPLETED and unseen, start processing
                |
                v
Fetch full order from Square
                |
                v
Project ingredient + packaging usage
                |
                v
Convert into Square stock-unit adjustments
                |
                v
Apply inventory change
                |
                v
Persist final state as applied / blocked / failed
```

Important operational detail:
- webhook delivery order is not trusted
- duplicate completed events are expected
- the app uses SQLite state to avoid processing the same order repeatedly

## Input / Output Example

### Input

A completed order like:

```json
{
  "name": "Tie Guan Yin Au Lait with Osmanthus Honey",
  "modifiers": ["Boba", "No Sugar"],
  "state": "COMPLETED"
}
```

### Projected Output

The system resolves that into usage roughly like:

```json
[
  {"inventory_key": "tgy", "amount": 5.33333, "unit": "g"},
  {"inventory_key": "milk", "amount": 150.0, "unit": "ml"},
  {"inventory_key": "boba", "amount": 100.0, "unit": "g"},
  {"inventory_key": "u600_cup", "amount": 1.0, "unit": "cup"},
  {"inventory_key": "big_straw", "amount": 1.0, "unit": "straw"}
]
```

### Inventory API Write

That is then converted into Square stock units before being sent to the Inventory API:

```json
[
  {"catalog_object_id": "DFSCYEJEFN4PTIKTE4YVJWLH", "quantity": "0.00889"},
  {"catalog_object_id": "4CLJVUZQCIVAEU4F7APU6QGX", "quantity": "0.03968"},
  {"catalog_object_id": "CVTORPM7SO6H5BLFDROJ5DLA", "quantity": "0.03333"},
  {"catalog_object_id": "RFKMPO65RYX5APBVM3CPEV5W", "quantity": "0.00100"},
  {"catalog_object_id": "NJZAOW4UF4CL5KRZBE32JHGH", "quantity": "0.00044"}
]
```

That distinction matters:
- recipe logic works in physical units
- Square inventory writes must respect the stock unit configured for each internal supply item

## Design Decisions

### 1. Config-driven recipe modeling

Recipes and internal inventory mappings live in JSON rather than hardcoded Python branches.

Why:
- menu changes are frequent
- drink logic is mostly data, not control flow
- operational tweaks should not require code rewrites

Key files:
- `data/recipe_map.json`
- `data/inventory_item_map.json`

### 2. Shared processor for webhook and CLI

The project originally leaned on scripts, but the core logic now lives in:
- `app/order_processor.py`

Why:
- webhook automation and manual replay should use the same code path
- duplicate logic between server and scripts is brittle
- this shape is closer to a deployable service

### 3. SQLite for lightweight workflow state

Processing state is tracked in:
- `data/order_processing.db`

Why:
- enough durability for local/internal deployment
- simpler than introducing Postgres too early
- gives replay, operator visibility, and duplicate-event protection

### 4. Inventory adjustments use `IN_STOCK -> WASTE`

The system applies positive-quantity Square inventory adjustments from:
- `IN_STOCK`
- to `WASTE`

Why:
- this is the valid Square adjustment model for consumption
- negative quantity writes were invalid

### 5. Stock-unit conversion happens at the API boundary

Projection math stays in recipe/inventory units until the final write step.

Why:
- keeps domain math readable
- preserves precision internally
- only converts and rounds when the Square API actually needs stock-unit quantities

## Idempotency and State Tracking

This is one of the most important parts of the system.

### Processing states

- `pending`
  - the order entered the workflow
- `blocked`
  - projection was incomplete or unsafe
- `failed`
  - processing attempted but did not finish successfully
- `applied`
  - inventory adjustment succeeded

### Why state tracking exists

Square webhooks can:
- arrive out of order
- retry on failure
- send multiple `COMPLETED` events for the same order

Without state tracking, the app could apply the same inventory depletion multiple times.

### Current protection model

- only `COMPLETED` orders are eligible
- webhook processing only starts when the order has no existing processing state
- replay is explicit and operator-driven
- inventory request idempotency keys are derived from:
  - order IDs
  - actual change-set contents

That design prevents two classes of bugs:
- accidental duplicate processing from repeated webhook delivery
- incorrect Square idempotency-key reuse when the request body changes

## Tech Stack

- Python
- FastAPI
- Square Python SDK / Square APIs
- SQLite
- JSON-based recipe and inventory configuration
- unittest for local regression coverage

## Additional Documentation

- [AWS cost analysis](docs/aws-cost-analysis.md)
- [Docs index](docs/README.md)

## Repository Structure

- `server.py`
  - FastAPI app, webhook entrypoint, static mount
- `app/order_processor.py`
  - shared end-to-end processing pipeline
- `app/order_inventory_projection.py`
  - recipe resolution and usage projection
- `app/order_processing_db.py`
  - SQLite processing-state helpers
- `app/inventory_stock_units.py`
  - display and stock-unit conversion logic
- `app/admin_routes.py`
  - lightweight admin and replay routes
- `scripts/`
  - CLI wrappers, inspection tools, replay tooling
- `testing/`
  - fixtures, live scenarios, regression tests
- `data/`
  - recipe and inventory mappings

## Running Locally

### Environment

Create a local `.env` from `.env.example`:

- `SQUARE_ACCESS_TOKEN`
- `SQUARE_ENVIRONMENT`
- `SQUARE_WEBHOOK_SIGNATURE_KEY`
- `SQUARE_WEBHOOK_NOTIFICATION_URL`

### Start the app

```bash
uvicorn server:app --reload --port 8000
```

### Admin console

```text
http://127.0.0.1:8000/admin/order-processing
```

### Useful commands

```bash
./.venv/bin/python -m scripts.search_orders
./.venv/bin/python -m scripts.inspect_order ORDER_ID
./.venv/bin/python -m scripts.apply_inventory_adjustments --apply ORDER_ID
./.venv/bin/python -m scripts.list_order_processing_states
./.venv/bin/python -m scripts.replay_order ORDER_ID
./.venv/bin/python -m scripts.replay_failed_orders
```

### Tests

```bash
./.venv/bin/python -m unittest testing.test_apply_inventory_adjustments testing.test_order_inventory_projection testing.test_inventory_stock_units
```

## Current Coverage

The modeled menu currently includes:
- cold drinks
- hot drinks
- brewed teas
- au lait and milk tea paths
- fruit drinks
- sugar-level scaling
- additive toppings
- built-in toppings
- batch-derived jelly and foam components
- cold and hot packaging rules

The current packaging model covers:
- `u600_cup`
- `small_straw`
- `big_straw`
- `cold_cup_lid`
- `hot_cup`
- `hot_lid`

## Limitations

- current mappings are Sandbox-focused
- the admin console is intentionally lightweight and unauthenticated
- the system is still optimized for local/internal deployment rather than hosted production
- alerting and reconciliation are not implemented yet
- older historical Sandbox orders can be noisy compared with controlled live scenarios

## Why This Is Worth Showing

This project grew beyond a simple API integration and became a small operations system.

It combines:
- event-driven processing
- configuration-driven recipe modeling
- stateful idempotent workflow design
- inventory-unit and stock-unit conversions
- internal operator tooling
- live external API integration

For an internship project built around a real menu and workflow, that felt like meaningful engineering scope.
