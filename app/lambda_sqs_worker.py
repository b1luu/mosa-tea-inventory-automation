import json

from app import order_processing_db
from app.webhook_worker import process_webhook_job


def _check_claim_lease_outlives_this_run(context):
    # A stale claim is taken over once it is CLAIM_LEASE_SECONDS old, which is
    # safe only because this Lambda is killed before then. At the start of an
    # invocation the remaining time is the configured timeout; if someone raises
    # the timeout past the lease, fail every invocation loudly (retries, then the
    # DLQ alarm) rather than let a live run be taken over by a retry.
    if context is None:
        return
    timeout_seconds = context.get_remaining_time_in_millis() / 1000
    if timeout_seconds >= order_processing_db.CLAIM_LEASE_SECONDS:
        raise RuntimeError(
            f"Worker timeout ({timeout_seconds:.0f} s) must be shorter than the "
            f"claim lease ({order_processing_db.CLAIM_LEASE_SECONDS} s); raise "
            f"CLAIM_LEASE_SECONDS in app/order_processing_db.py."
        )


def lambda_handler(event, context):
    _check_claim_lease_outlives_this_run(context)
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            job = json.loads(record["body"])
            process_webhook_job(job)
        except Exception:
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
