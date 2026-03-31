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
