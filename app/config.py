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

def get_square_webhook_signature_key():
    signature_key = os.getenv("SQUARE_WEBHOOK_SIGNATURE_KEY")
    if not signature_key:
        raise ValueError(
            "Missing Webhook Signature Key"
        )
    return signature_key 

def get_square_webhook_notification_url():
    notification_url = os.getenv("SQUARE_WEBHOOK_NOTIFICATION_URL")
    if not notification_url:
        raise ValueError(
            "Missing correct URL for webhook"
        )
    return notification_url



