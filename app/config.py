import os

from dotenv import load_dotenv

load_dotenv()


def get_square_access_token():
    access_token = os.getenv("SQUARE_ACCESS_TOKEN")
    if not access_token:
        raise ValueError(
            "Missing required environment variable: SQUARE_ACCESS_TOKEN. "
            "Set it in your environment or .env file before running the script."
        )
    return access_token


def get_square_environment_name():
    environment_name = os.getenv("SQUARE_ENVIRONMENT", "sandbox").strip().lower()
    if environment_name not in {"sandbox", "production"}:
        raise ValueError(
            "Invalid SQUARE_ENVIRONMENT value. Use 'sandbox' or 'production'."
        )
    return environment_name


def get_webhook_dispatch_mode():
    dispatch_mode = os.getenv("WEBHOOK_DISPATCH_MODE", "local").strip().lower()
    if dispatch_mode not in {"local", "sqs"}:
        raise ValueError(
            "Invalid WEBHOOK_DISPATCH_MODE value. Use 'local' or 'sqs'."
        )
    return dispatch_mode


def get_aws_region():
    region = os.getenv("AWS_REGION")
    if not region:
        raise ValueError(
            "Missing required environment variable: AWS_REGION. "
            "Set it before using AWS-backed dispatch."
        )
    return region.strip()


def get_webhook_job_queue_url():
    queue_url = os.getenv("WEBHOOK_JOB_QUEUE_URL")
    if not queue_url:
        raise ValueError(
            "Missing required environment variable: WEBHOOK_JOB_QUEUE_URL. "
            "Set it before using SQS-backed dispatch."
        )
    return queue_url.strip()


def get_square_webhook_signature_key():
    signature_key = os.getenv("SQUARE_WEBHOOK_SIGNATURE_KEY")
    if not signature_key:
        raise ValueError(
            "Missing required environment variable: SQUARE_WEBHOOK_SIGNATURE_KEY. "
            "Set it in your environment or .env file before running the webhook server."
        )
    return signature_key


def get_square_webhook_notification_url():
    notification_url = os.getenv("SQUARE_WEBHOOK_NOTIFICATION_URL")
    if not notification_url:
        raise ValueError(
            "Missing required environment variable: SQUARE_WEBHOOK_NOTIFICATION_URL. "
            "Set it in your environment or .env file before running the webhook server."
        )
    return notification_url
