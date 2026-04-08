# Mosa Tea Inventory Automation

Turns completed Square drink orders into raw ingredient and packaging depletion.

This project exists because POS sales are not the same thing as inventory consumption. A single drink sale can imply tea leaves, milk, sugar-level rules, toppings, foam, cups, lids, and straws. This service maps that gap and writes the resulting inventory adjustments back to Square.

## Architecture

```text
                                   +---------------------------+
                                   |          Square           |
                                   |---------------------------|
                                   | OAuth / Consent           |
                                   | Orders API                |
                                   | Inventory API             |
                                   | Order Webhooks            |
                                   +-------------+-------------+
                                                 |
                                                 v
+-------------------------------------------------------------------------------------------+
|                      FastAPI / API Gateway Webhook Ingress                                |
|-------------------------------------------------------------------------------------------|
| verify signature | normalize payload | record event | reserve order | acknowledge Square  |
+---------------------------+--------------------------------+------------------------------+
                            |                                |
                            | writes state                   | enqueues async job
                            v                                v
                +---------------------------+      +------------------------------+
                | Webhook Event Store       |      | SQS Webhook Jobs Queue       |
                | SQLite or DynamoDB        |      | retries + redrive to DLQ     |
                +---------------------------+      +---------------+--------------+
                                                                   |
                                                                   v
                                                      +----------------------------+
                                                      | Lambda / Worker            |
                                                      |----------------------------|
                                                      | fetch full order           |
                                                      | resolve merchant auth      |
                                                      | resolve approved binding   |
                                                      | project recipe usage       |
                                                      | write Square inventory     |
                                                      +-----+-----------+----------+
                                                            |           |
                                                            | reads     | updates
                                                            v           v
                                  +---------------------------+   +--------------------------+
                                  | Merchant Store            |   | Order Processing Store   |
                                  | SQLite local or           |   | SQLite or DynamoDB       |
                                  | DynamoDB + Secrets        |   +--------------------------+
                                  +-------------+-------------+
                                                |
                             +------------------+------------------+
                             |                                     |
                             v                                     v
                 +---------------------------+         +---------------------------+
                 | Approved Bindings         |         | Recipe + Inventory JSON   |
                 | merchant/location mapping |         | canonical recipe rules     |
                 +---------------------------+         +---------------------------+
```


## Current Shape

- Config-driven recipe and inventory modeling in JSON
- Idempotent order processing with persisted state
- Webhook event ledger for duplicate/retry control
- OAuth merchant onboarding with token refresh and revoke handling
- Merchant-aware runtime with approved binding and write-enable gates
- Local mode with SQLite
- AWS-backed mode with SQS, Lambda, DynamoDB, Secrets Manager, and DLQ
- GitHub Actions CI plus manual Lambda deploy workflow

## Stack

- Python
- FastAPI
- Square Orders / Inventory APIs
- SQS
- Lambda
- DynamoDB
- SQLite
- `unittest`

## Run Locally

Create `.env` from `.env.example` and set:

- `SQUARE_ACCESS_TOKEN`
- `SQUARE_ENVIRONMENT`
- `SQUARE_WEBHOOK_SIGNATURE_KEY`
- `SQUARE_WEBHOOK_NOTIFICATION_URL`

Optional runtime mode config:

- `WEBHOOK_DISPATCH_MODE=local|sqs`
- `ORDER_PROCESSING_STORE_MODE=sqlite|dynamodb`
- `WEBHOOK_EVENT_STORE_MODE=sqlite|dynamodb`
- `AWS_REGION`
- `WEBHOOK_JOB_QUEUE_URL`
- `DYNAMODB_ORDER_PROCESSING_TABLE`
- `DYNAMODB_WEBHOOK_EVENT_TABLE`

Start the server:

```bash
uvicorn server:app --reload --port 8000
```

## Useful Commands

```bash
./.venv/bin/python -m unittest discover -s testing -p 'test_*.py'
./.venv/bin/python -m scripts.search_orders
./.venv/bin/python -m scripts.inspect_order ORDER_ID
./.venv/bin/python -m scripts.process_sqs_webhook_job
./.venv/bin/python -m scripts.replay_order ORDER_ID
./.venv/bin/python -m testing.create_live_test_order --pay roasted_buckwheat_barley_milk_tea_100_sugar
```

## Live Demo

Use one real Sandbox order to watch the event-driven path end to end.

1. Tail ingress logs:

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-ingress --since 15m --follow
```

2. Tail worker logs:

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-worker --since 15m --follow
```

3. Run one live canary:

```bash
./.venv/bin/python -m testing.run_live_cloud_canary tgy_tea_100_sugar
```

4. Check the queue is drained after processing:

```bash
aws --no-cli-pager sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/541341197059/mosa-tea-webhook-jobs \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

5. Verify the updated Square inventory directly:

```bash
./.venv/bin/python -m scripts.inspect_inventory_count --inventory-key tgy
```

Expected success signals:

- Ingress logs show `order.created` / `order.updated` webhook receipts, then duplicate deliveries being ignored.
- Worker logs show one invocation for the completed order.
- Canary output moves `processing_state` from `null` to `pending` to `processing` to `applied`.
- Canary ends with `canary_complete | success=true`.
- SQS shows `ApproximateNumberOfMessages=0` and `ApproximateNumberOfMessagesNotVisible=0`.
- `inspect_inventory_count` matches the canary's `inventory_after` values.

## Key Files

- `server.py`: Square webhook entrypoint
- `app/order_processor.py`: shared processing pipeline
- `app/webhook_worker.py`: queue job execution
- `app/lambda_sqs_worker.py`: Lambda handler
- `app/order_inventory_projection.py`: recipe resolution and usage projection
- `app/order_processing_store.py`: order-processing state abstraction
- `app/webhook_event_store.py`: webhook event state abstraction
- `data/recipe_map.json`: drink recipes and rules
- `data/inventory_item_map.json`: inventory item mappings

## Docs

- [Docs index](docs/README.md)
- [API Gateway serverless ingress](docs/api-gateway-serverless-ingress.md)
- [AWS cost analysis](docs/aws-cost-analysis.md)
- [SQS dead-letter queue behavior](docs/sqs-dlq-behavior.md)

## Status

This is no longer just a local script project. It now has a production-shaped event pipeline, live AWS integration, CI, deploy workflow, DLQ handling, and real end-to-end sandbox validation.
