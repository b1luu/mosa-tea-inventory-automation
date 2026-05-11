import asyncio
import base64
from urllib.parse import urlencode

from app.oauth_app import oauth_app


def _get_method(event):
    return (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "GET"
    )


def _get_path(event):
    return (
        event.get("rawPath")
        or event.get("path")
        or event.get("requestContext", {}).get("http", {}).get("path")
        or "/"
    )


def _get_query_string(event):
    raw_query_string = event.get("rawQueryString")
    if raw_query_string is not None:
        return raw_query_string

    query_params = event.get("queryStringParameters") or {}
    return urlencode(query_params, doseq=True)


def _get_request_body(event):
    body = event.get("body") or ""
    if not event.get("isBase64Encoded"):
        return body.encode("utf-8")
    return base64.b64decode(body)


async def _invoke_oauth_app(method, path, query_string, headers, body):
    messages = []
    body_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string.encode("utf-8"),
        "headers": [
            (name.lower().encode("utf-8"), value.encode("utf-8"))
            for name, value in (headers or {}).items()
        ],
        "client": ("127.0.0.1", 0),
        "server": ("lambda", 443),
    }

    async def receive():
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await oauth_app(scope, receive, send)
    return messages


def _build_lambda_response(messages):
    status_code = None
    headers = {}
    body_chunks = []

    for message in messages:
        message_type = message["type"]
        if message_type == "http.response.start":
            status_code = message["status"]
            for name, value in message.get("headers", []):
                headers[name.decode("utf-8")] = value.decode("utf-8")
        elif message_type == "http.response.body":
            body_chunks.append(message.get("body", b""))

    if status_code is None:
        raise RuntimeError("OAuth Lambda handler did not receive an HTTP response.")

    return {
        "statusCode": status_code,
        "headers": headers,
        "body": b"".join(body_chunks).decode("utf-8"),
        "isBase64Encoded": False,
    }


def lambda_handler(event, context):
    messages = asyncio.run(
        _invoke_oauth_app(
            _get_method(event),
            _get_path(event),
            _get_query_string(event),
            event.get("headers") or {},
            _get_request_body(event),
        )
    )
    return _build_lambda_response(messages)
