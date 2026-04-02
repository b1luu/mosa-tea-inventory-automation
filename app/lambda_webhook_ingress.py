import base64
import json

from app.webhook_ingress import handle_square_webhook_request


def _get_header(headers, key):
    if not headers:
        return ""

    key_lower = key.lower()
    for header_name, value in headers.items():
        if header_name.lower() == key_lower:
            return value
    return ""


def _get_raw_request_body(event):
    body = event.get("body") or ""
    if not event.get("isBase64Encoded"):
        return body

    return base64.b64decode(body).decode("utf-8")


def lambda_handler(event, context):
    request_body = _get_raw_request_body(event)
    signature_header = _get_header(
        event.get("headers"),
        "x-square-hmacsha256-signature",
    )
    response = handle_square_webhook_request(
        request_body=request_body,
        signature_header=signature_header,
    )
    return {
        "statusCode": response.status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(response.body),
    }
