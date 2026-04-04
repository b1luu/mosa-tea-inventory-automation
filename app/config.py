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


def get_square_oauth_client_id():
    client_id = os.getenv("SQUARE_OAUTH_CLIENT_ID")
    if not client_id:
        raise ValueError(
            "Missing required environment variable: SQUARE_OAUTH_CLIENT_ID. "
            "Set it before using Square OAuth onboarding."
        )
    return client_id.strip()


def get_square_oauth_client_secret():
    client_secret = os.getenv("SQUARE_OAUTH_CLIENT_SECRET")
    if not client_secret:
        raise ValueError(
            "Missing required environment variable: SQUARE_OAUTH_CLIENT_SECRET. "
            "Set it before using Square OAuth onboarding."
        )
    return client_secret.strip()


def get_square_oauth_redirect_uri():
    redirect_uri = os.getenv("SQUARE_OAUTH_REDIRECT_URI")
    if not redirect_uri:
        raise ValueError(
            "Missing required environment variable: SQUARE_OAUTH_REDIRECT_URI. "
            "Set it before using Square OAuth onboarding."
        )
    return redirect_uri.strip()


def get_square_oauth_scopes():
    scopes_value = os.getenv(
        "SQUARE_OAUTH_SCOPES",
        "MERCHANT_PROFILE_READ,ORDERS_READ,INVENTORY_READ,INVENTORY_WRITE,ITEMS_READ",
    )
    scopes = [scope.strip() for scope in scopes_value.split(",") if scope.strip()]
    if not scopes:
        raise ValueError(
            "SQUARE_OAUTH_SCOPES must define at least one scope."
        )
    return scopes


def get_webhook_dispatch_mode():
    dispatch_mode = os.getenv("WEBHOOK_DISPATCH_MODE", "local").strip().lower()
    if dispatch_mode not in {"local", "sqs"}:
        raise ValueError(
            "Invalid WEBHOOK_DISPATCH_MODE value. Use 'local' or 'sqs'."
        )
    return dispatch_mode


def get_order_processing_store_mode():
    store_mode = os.getenv("ORDER_PROCESSING_STORE_MODE", "sqlite").strip().lower()
    if store_mode not in {"sqlite", "dynamodb"}:
        raise ValueError(
            "Invalid ORDER_PROCESSING_STORE_MODE value. Use 'sqlite' or 'dynamodb'."
        )
    return store_mode


def get_webhook_event_store_mode():
    store_mode = os.getenv("WEBHOOK_EVENT_STORE_MODE", "sqlite").strip().lower()
    if store_mode not in {"sqlite", "dynamodb"}:
        raise ValueError(
            "Invalid WEBHOOK_EVENT_STORE_MODE value. Use 'sqlite' or 'dynamodb'."
        )
    return store_mode


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


def get_dynamodb_order_processing_table_name():
    table_name = os.getenv("DYNAMODB_ORDER_PROCESSING_TABLE")
    if not table_name:
        raise ValueError(
            "Missing required environment variable: DYNAMODB_ORDER_PROCESSING_TABLE. "
            "Set it before using DynamoDB-backed order processing state."
        )
    return table_name.strip()


def get_dynamodb_webhook_event_table_name():
    table_name = os.getenv("DYNAMODB_WEBHOOK_EVENT_TABLE")
    if not table_name:
        raise ValueError(
            "Missing required environment variable: DYNAMODB_WEBHOOK_EVENT_TABLE. "
            "Set it before using DynamoDB-backed webhook event state."
        )
    return table_name.strip()


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
