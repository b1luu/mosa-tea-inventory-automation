import json

from app.config import get_aws_region, get_webhook_job_queue_url


def _create_sqs_client():
    import boto3

    return boto3.client("sqs", region_name=get_aws_region())


def dispatch_webhook_job_to_sqs(job):
    client = _create_sqs_client()
    return client.send_message(
        QueueUrl=get_webhook_job_queue_url(),
        MessageBody=json.dumps(job),
    )


def receive_webhook_jobs(max_number_of_messages=1, wait_time_seconds=20):
    client = _create_sqs_client()
    response = client.receive_message(
        QueueUrl=get_webhook_job_queue_url(),
        MaxNumberOfMessages=max_number_of_messages,
        WaitTimeSeconds=wait_time_seconds,
    )
    return response.get("Messages", [])


def delete_webhook_job(receipt_handle):
    client = _create_sqs_client()
    return client.delete_message(
        QueueUrl=get_webhook_job_queue_url(),
        ReceiptHandle=receipt_handle,
    )


def change_webhook_job_visibility(receipt_handle, visibility_timeout):
    client = _create_sqs_client()
    return client.change_message_visibility(
        QueueUrl=get_webhook_job_queue_url(),
        ReceiptHandle=receipt_handle,
        VisibilityTimeout=visibility_timeout,
    )
