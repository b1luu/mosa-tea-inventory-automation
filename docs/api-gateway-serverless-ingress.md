# API Gateway Serverless Ingress

This project now supports a fully serverless webhook path:

```text
Square -> API Gateway -> webhook ingress Lambda -> SQS -> worker Lambda
```

## Lambdas

- Worker Lambda handler:
  - `app.lambda_sqs_worker.lambda_handler`
- Webhook ingress Lambda handler:
  - `app.lambda_webhook_ingress.lambda_handler`

Both functions can deploy from the same package because they share the same `app/` code.

## GitHub Actions Deploy Variables

Set these repository variables:

- `AWS_REGION`
- `WORKER_LAMBDA_FUNCTION_NAME`
- `WEBHOOK_INGRESS_LAMBDA_FUNCTION_NAME`

Legacy compatibility:

- `LAMBDA_FUNCTION_NAME` still works for the worker Lambda, but `WORKER_LAMBDA_FUNCTION_NAME` is preferred.

Set this repository secret:

- `AWS_ROLE_TO_ASSUME`

The workflow in [deploy-lambda.yml](../.github/workflows/deploy-lambda.yml) builds a Linux-compatible package and deploys it to both functions.

## Webhook Ingress Lambda Environment

Set:

- `SQUARE_WEBHOOK_SIGNATURE_KEY`
- `SQUARE_WEBHOOK_NOTIFICATION_URL`
- `WEBHOOK_DISPATCH_MODE=sqs`
- `ORDER_PROCESSING_STORE_MODE=dynamodb`
- `WEBHOOK_EVENT_STORE_MODE=dynamodb`
- `WEBHOOK_JOB_QUEUE_URL`
- `DYNAMODB_ORDER_PROCESSING_TABLE`
- `DYNAMODB_WEBHOOK_EVENT_TABLE`
- `SQUARE_ACCESS_TOKEN`
- `SQUARE_ENVIRONMENT`

Do not manually set:

- `AWS_REGION`

Lambda already provides it.

## Worker Lambda Environment

Set:

- `SQUARE_ACCESS_TOKEN`
- `SQUARE_ENVIRONMENT`
- `ORDER_PROCESSING_STORE_MODE=dynamodb`
- `WEBHOOK_EVENT_STORE_MODE=dynamodb`
- `DYNAMODB_ORDER_PROCESSING_TABLE`
- `DYNAMODB_WEBHOOK_EVENT_TABLE`

The worker Lambda does not need:

- `SQUARE_WEBHOOK_SIGNATURE_KEY`
- `SQUARE_WEBHOOK_NOTIFICATION_URL`

## API Gateway Setup

Use an HTTP API.

Create:

- Route:
  - `POST /webhook/square`
- Integration:
  - webhook ingress Lambda
- Payload format version:
  - `2.0`

Then use the resulting public URL as:

- the Square webhook notification URL
- the value of `SQUARE_WEBHOOK_NOTIFICATION_URL`

These must match exactly for signature verification.

## IAM Split

Webhook ingress Lambda execution role needs:

- CloudWatch Logs
- `sqs:SendMessage` on the webhook jobs queue
- DynamoDB read/write on:
  - order-processing table
  - webhook-events table

Worker Lambda execution role needs:

- CloudWatch Logs
- SQS consume permissions on the webhook jobs queue
- DynamoDB read/write on:
  - order-processing table
  - webhook-events table

## Verification Rules

The ingress path verifies Square webhooks using:

- the raw request body
- the exact notification URL
- the stored Square signature key
- `x-square-hmacsha256-signature`

JSON parsing happens only after signature verification succeeds.

## Local Development

FastAPI still exists for local testing and admin routes.

That means:

- local/dev:
  - FastAPI route in [server.py](../server.py)
- cloud/prod-style ingress:
  - API Gateway + [lambda_webhook_ingress.py](../app/lambda_webhook_ingress.py)

Both paths share the same ingress logic in [webhook_ingress.py](../app/webhook_ingress.py).
