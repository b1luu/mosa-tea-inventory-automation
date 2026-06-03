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
    # API Gateway HTTP API (v2 payload) requires Set-Cookie to be returned in
    # the top-level `cookies` array. If we instead stuff it into the `headers`
    # dict alongside everything else, API Gateway silently drops it — which
    # breaks any flow that depends on the browser receiving a cookie (e.g.
    # the operator session cookie issued by POST /onboarding).
    cookies = []
    body_chunks = []

    for message in messages:
        message_type = message["type"]
        if message_type == "http.response.start":
            status_code = message["status"]
            for raw_name, raw_value in message.get("headers", []):
                name = raw_name.decode("utf-8")
                value = raw_value.decode("utf-8")
                if name.lower() == "set-cookie":
                    cookies.append(value)
                else:
                    headers[name] = value
        elif message_type == "http.response.body":
            body_chunks.append(message.get("body", b""))

    if status_code is None:
        raise RuntimeError("OAuth Lambda handler did not receive an HTTP response.")

    response = {
        "statusCode": status_code,
        "headers": headers,
        "body": b"".join(body_chunks).decode("utf-8"),
        "isBase64Encoded": False,
    }
    if cookies:
        response["cookies"] = cookies
    return response


def _merge_incoming_cookies(headers, event):
    """API Gateway HTTP API (v2 payload) strips the `Cookie` request header into
    a separate top-level ``cookies`` array. Without merging it back, FastAPI's
    ``request.cookies`` is always empty — so any cookie-based flow (e.g. the
    operator session) is silently broken even though the cookie was sent.

    Returns a new headers dict with the merged Cookie header (if any).
    """
    merged = dict(headers or {})
    incoming = event.get("cookies") or []
    if incoming and not any(k.lower() == "cookie" for k in merged):
        merged["cookie"] = "; ".join(incoming)
    return merged


def lambda_handler(event, context):
    messages = asyncio.run(
        _invoke_oauth_app(
            _get_method(event),
            _get_path(event),
            _get_query_string(event),
            _merge_incoming_cookies(event.get("headers") or {}, event),
            _get_request_body(event),
        )
    )
    return _build_lambda_response(messages)
