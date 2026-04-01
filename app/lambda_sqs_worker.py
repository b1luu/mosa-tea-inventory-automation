import json

from app.webhook_worker import process_webhook_job


def lambda_handler(event, context):
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            job = json.loads(record["body"])
            process_webhook_job(job)
        except Exception:
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
