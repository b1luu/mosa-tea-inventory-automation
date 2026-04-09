import base64
from decimal import Decimal
import json
from secrets import compare_digest

from app.config import get_operator_api_token
from app.manual_count_sync import sync_manual_inventory_counts_batch


def _get_header(headers, key):
    if not headers:
        return ""

    key_lower = key.lower()
    for header_name, value in headers.items():
        if header_name.lower() == key_lower:
            return value
    return ""


def _extract_bearer_token(authorization):
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _get_raw_request_body(event):
    body = event.get("body") or ""
    if not event.get("isBase64Encoded"):
        return body

    return base64.b64decode(body).decode("utf-8")


def _json_response(status_code, body, headers=None):
    response_headers = {"content-type": "application/json"}
    if headers:
        response_headers.update(headers)

    def _json_default(value):
        if isinstance(value, Decimal):
            return str(value)
        raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")

    return {
        "statusCode": status_code,
        "headers": response_headers,
        "body": json.dumps(body, default=_json_default),
    }


def _authorize_operator_request(event):
    try:
        expected_token = get_operator_api_token()
    except ValueError as error:
        return _json_response(503, {"detail": str(error)})

    query = event.get("queryStringParameters") or {}
    authorization = _get_header(event.get("headers"), "authorization")
    provided_token = (
        _get_header(event.get("headers"), "x-operator-token")
        or query.get("operator_token")
        or _extract_bearer_token(authorization)
    )

    if not provided_token or not compare_digest(provided_token, expected_token):
        return _json_response(
            401,
            {"detail": "Invalid or missing operator token."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return None


def lambda_handler(event, context):
    unauthorized_response = _authorize_operator_request(event)
    if unauthorized_response is not None:
        return unauthorized_response

    try:
        body = json.loads(_get_raw_request_body(event) or "{}")
    except json.JSONDecodeError:
        return _json_response(400, {"detail": "Request body must be valid JSON."})

    try:
        rows = [
            {
                "inventory_key": row["inventory_key"],
                "counted_quantity": row["counted_quantity"],
                "counted_unit": row["counted_unit"],
                "source_reference": row.get("source_reference"),
            }
            for row in body["rows"]
        ]
        result = sync_manual_inventory_counts_batch(
            environment=body["environment"],
            merchant_id=body["merchant_id"],
            location_id=body["location_id"],
            rows=rows,
            apply_changes=bool(body.get("apply_changes", False)),
        )
    except KeyError as error:
        return _json_response(
            400,
            {"detail": f"Missing required field: {error.args[0]}"},
        )
    except ValueError as error:
        return _json_response(400, {"detail": str(error)})

    return _json_response(200, result)
