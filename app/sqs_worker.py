import json

from app.order_processing_store import (
    PROCESSING_STATE_APPLIED,
    PROCESSING_STATE_BLOCKED,
    get_order_processing_state,
)
from app.sqs_dispatcher import delete_webhook_job, receive_webhook_jobs
from app.webhook_worker import process_webhook_job


def process_one_sqs_message():
    messages = receive_webhook_jobs(max_number_of_messages=1)
    if not messages:
        return {"message": "No webhook jobs available."}

    message = messages[0]
    job = json.loads(message["Body"])
    order_id = job["order_id"]
    process_webhook_job(job)
    processing_state = get_order_processing_state(order_id)

    if processing_state not in {PROCESSING_STATE_APPLIED, PROCESSING_STATE_BLOCKED}:
        raise RuntimeError(
            f"Webhook job for order '{order_id}' did not reach a terminal deletable state. "
            f"Current processing state: {processing_state!r}."
        )

    delete_webhook_job(message["ReceiptHandle"])

    return {
        "message_id": message["MessageId"],
        "job": job,
        "processing_state": processing_state,
        "deleted": True,
    }
