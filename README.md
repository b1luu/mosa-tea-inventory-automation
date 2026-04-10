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
- Google Sheets batch manual inventory sync through API Gateway + Lambda
- OAuth merchant onboarding with token refresh and revoke handling
- Merchant-aware runtime with approved binding and write-enable gates
- Local mode with SQLite
- AWS-backed mode with SQS, Lambda, DynamoDB, Secrets Manager, and DLQ
- Public-safe Terraform scaffold for the AWS footprint
- GitHub Actions CI plus manual Lambda deploy workflow

## Stack

- Python
- FastAPI
- Google Apps Script
- Square Orders / Inventory APIs
- API Gateway
- SQS
- Lambda
- DynamoDB
- SQLite
- Terraform
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
  --queue-url https://sqs.us-west-2.amazonaws.com/account#/mosa-tea-webhook-jobs \
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

Sanitized example output:

```text
$ ./.venv/bin/python -m testing.run_live_cloud_canary tgy_tea_100_sugar
canary_started | scenario_name="tgy_tea_100_sugar" | location_id="LOCATION_DEMO" | timeout_seconds=120 | poll_seconds=3
order_created | order_id="order_demo_123" | payment_id="payment_demo_123" | payment_status="COMPLETED"
waiting_for_aws_pipeline | attempt=1 | order_id="order_demo_123" | processing_state=null | processed_count=0 | failed_count=0 | total_events=0
waiting_for_aws_pipeline | attempt=2 | order_id="order_demo_123" | processing_state="pending" | processed_count=0 | failed_count=0 | total_events=3
waiting_for_aws_pipeline | attempt=3 | order_id="order_demo_123" | processing_state="processing" | processed_count=0 | failed_count=0 | total_events=4
aws_pipeline_settled | order_id="order_demo_123" | processing_state="applied" | webhook_event_summary={"failed_count": 0, "processed_count": 1, "status_counts": {"ignored": 3, "processed": 1}, "total": 4}
inventory_counts_settled | inventory_keys=["small_straw", "sugar_syrup", "tgy", "u600_cup"]
canary_complete | order_id="order_demo_123" | success=true
```

```text
$ aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-ingress --since 15m
... START RequestId: req_demo_ingress_1 Version: $LATEST
... order_webhook:
... {
...   "event_type": "order.updated",
...   "order_id": "order_demo_123",
...   "state": "COMPLETED",
...   "merchant_status": "active",
...   "current_processing_state": "pending",
...   "processing_state_after": "pending"
... }
... END RequestId: req_demo_ingress_1
```

```text
$ aws --no-cli-pager logs tail /aws/lambda/mosa-tea-webhook-worker --since 15m
... START RequestId: req_demo_worker_1 Version: $LATEST
... END RequestId: req_demo_worker_1
... REPORT RequestId: req_demo_worker_1 Duration: 6200.00 ms Billed Duration: 7300 ms
```

```text
$ aws --no-cli-pager sqs get-queue-attributes --queue-url ... --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
{
  "Attributes": {
    "ApproximateNumberOfMessages": "0",
    "ApproximateNumberOfMessagesNotVisible": "0"
  }
}
```

```text
$ ./.venv/bin/python -m scripts.inspect_inventory_count --inventory-key tgy
summary:
{
  "inventory_key": "tgy",
  "in_stock_quantity": "111.98667",
  "waste_quantity": "0.31552"
}
```

## Manual Inventory Sync

The project also supports operator-driven inventory recount sync from Google Sheets.

```text
Google Sheets button -> Apps Script batch request -> API Gateway -> manual count sync Lambda -> Square Inventory API
```

Manual sync is intentionally separate from the order webhook pipeline:

- order automation handles depletion caused by completed drink sales
- manual sync handles physical recount reconciliation from the sheet

Current operator model:

- `Sheet1` stores item names, canonical `inventory_key` values, and dated inventory history columns
- the Apps Script reads all tracked rows in one pass
- highlighted "added stock" cells are ignored
- the latest non-highlighted count per row is used as the physical count source
- blank `inventory_key` rows are skipped so intentionally untracked items can stay in the sheet

AWS path:

- API route:
  - `POST /admin/api/manual-count-sync-batch`
- Lambda handler:
  - `app.lambda_manual_count_sync.lambda_handler`
- auth:
  - `X-Operator-Token`

Google Sheets setup:

- store `SYNC_URL` in Script Properties and point it at the full API Gateway route
- store `SYNC_TOKEN` in Script Properties and keep it aligned with the Lambda `OPERATOR_API_TOKEN`
- assign the sheet button to:
  - `syncAllTeasParallel`

Expected success behavior:

- the Apps Script popup reports one batch summary plus per-row outcomes
- unchanged rows report that Square already matches the sheet count
- changed rows report the updated counted quantity and unit
- the Lambda completes in one request rather than one request per inventory row

Useful verification commands:

```bash
aws --no-cli-pager logs tail /aws/lambda/mosa-tea-manual-count-sync --since 10m --follow
```

```bash
curl -i -X POST "https://YOUR_API_ID.execute-api.us-west-2.amazonaws.com/admin/api/manual-count-sync-batch" \
  -H "Content-Type: application/json" \
  -H "X-Operator-Token: YOUR_OPERATOR_TOKEN" \
  -d '{
    "environment": "sandbox",
    "merchant_id": "YOUR_MERCHANT_ID",
    "location_id": "YOUR_LOCATION_ID",
    "apply_changes": false,
    "rows": [
      {
        "inventory_key": "black_tea",
        "counted_quantity": "80",
        "counted_unit": "bag",
        "source_reference": "Sheet1!AG2"
      }
    ]
  }'
```

## Key Files

- `server.py`: Square webhook entrypoint
- `app/lambda_manual_count_sync.py`: Lambda handler for Google Sheets batch recount sync
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
- [Terraform infrastructure](docs/terraform-infrastructure.md)

## Status

This is no longer just a local script project. It now has a production-shaped event pipeline, live AWS integration, CI, deploy workflow, DLQ handling, and real end-to-end sandbox validation.
