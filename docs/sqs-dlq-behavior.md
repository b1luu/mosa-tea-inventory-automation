# SQS Dead-Letter Queue Behavior

This project uses a main SQS queue for normal webhook jobs:

- `mosa-tea-webhook-jobs`

and a dead-letter queue (DLQ) for jobs that keep failing:

- `mosa-tea-webhook-jobs-dlq`

## What a DLQ Is

A dead-letter queue is a holding area for messages that could not be processed successfully after repeated attempts.

In this project, that means:

1. a webhook job is sent to the main queue
2. a worker tries to process it
3. the job keeps failing
4. after the queue's `maxReceiveCount` is reached, SQS moves that message to the DLQ

The DLQ prevents one bad message from retrying forever in the main queue.

## Why This Exists

Webhook systems eventually encounter poison messages.

Examples:
- malformed JSON in the queue body
- a job missing required fields like `order_id`
- a fake or nonexistent order ID
- a job whose order never reaches a terminal state
- persistent downstream failures

Without a DLQ, those messages would keep cycling in the main queue and add operational noise.

## What Counts As Success

From SQS's point of view, a job succeeds when `process_webhook_job` returns without raising. That happens when the order ends in any state in `TERMINAL_PROCESSING_STATES` (`app/webhook_worker.py`):

- `applied` — inventory changes were written to Square
- `blocked` — a write-readiness gate or unmapped line item stopped the write
- `failed` — the Square inventory call returned an error
- `cancelled_before_apply` — the order was cancelled during the hold, before apply

All four are terminal: the message is acknowledged and removed from the queue, and a later duplicate delivery for the same order is a no-op.

Note that `failed` is terminal but not a happy outcome. The worker records it in the order state and marks the webhook event `FAILED`, but the message does **not** go to the DLQ. Recover these with `scripts/replay_failed_orders.py` or `scripts/replay_order.py`.

A job is reported to SQS as failed (via `batchItemFailures` in `app/lambda_sqs_worker.py`) when the worker raises instead:

- `RetryableWebhookJobError` — the order could not be claimed and is not yet terminal (for example, another worker is still `processing` it)
- any other exception — malformed body, missing `order_id`, unresolved merchant context, a failed state transition, and so on; the processing claim is released first so a retry can claim it again

Those messages are retried and, after `maxReceiveCount` receives (`webhook_queue_max_receive_count`, default `3`), moved to the DLQ.

## Main Queue vs DLQ

Main queue:
- normal work
- expected to drain continuously

DLQ:
- failed work
- expected to be inspected manually
- should usually contain zero messages during normal operation

## Current Failure Flow

```text
Square webhook
  -> main queue
  -> worker attempts processing
  -> success: message is removed
  -> failure: message is retried
  -> repeated failure: SQS moves message to DLQ
```

## Recommended Queue Settings

Main queue:
- type: `Standard`
- dead-letter queue: enabled
- max receives: `3`

DLQ:
- type: `Standard`
- retention period: `14 days`

## Useful Commands

Main queue counts:

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/123456789012/mosa-tea-webhook-jobs \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

DLQ counts:

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/123456789012/mosa-tea-webhook-jobs-dlq \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

Process one main-queue job locally:

```bash
./.venv/bin/python -m scripts.process_sqs_webhook_job
```

Delete one queued job by order ID:

```bash
./.venv/bin/python -m scripts.delete_sqs_job_by_order_id ORDER_ID
```

Reset local runtime state:

```bash
./.venv/bin/python -m scripts.reset_runtime_state
```

## Operational Interpretation

If the main queue grows:
- the worker is not keeping up
- or something is failing before deletion

If the DLQ grows:
- a specific class of message is persistently bad
- inspect those messages before replaying or redriving them

The DLQ is a safety boundary, not part of the happy path.
