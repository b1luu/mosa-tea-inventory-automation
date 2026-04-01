import json

from app.sqs_dispatcher import delete_webhook_job, receive_webhook_jobs
from app.webhook_worker import process_webhook_job


def process_one_sqs_message():
    messages = receive_webhook_jobs(max_number_of_messages=1)
    if not messages:
        return {"message": "No webhook jobs available."}

    message = messages[0]
    job = json.loads(message["Body"])
    processing_state = process_webhook_job(job)

    delete_webhook_job(message["ReceiptHandle"])

    return {
        "message_id": message["MessageId"],
        "job": job,
        "processing_state": processing_state,
        "deleted": True,
    }
