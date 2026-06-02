import time
from datetime import datetime, timezone
from html import escape
from secrets import compare_digest
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from square.core.api_error import ApiError

from app.config import get_operator_api_token, get_square_environment_name
from app.merchant_store import (
    get_merchant_auth_record,
    get_merchant_write_readiness,
    list_merchant_contexts,
    refresh_oauth_merchant_access_token,
    upsert_oauth_merchant,
)
from app.oauth_state_store import consume_oauth_state, create_oauth_state
from app.operator_auth import require_operator_access
from app.operator_session import (
    COOKIE_NAME as OPERATOR_SESSION_COOKIE,
    issue_session_value,
    set_session_cookie,
    verify_session_value,
)
from app.square_oauth import (
    build_square_oauth_authorization_url,
    choose_default_location_id,
    exchange_authorization_code,
    list_locations_for_merchant,
    retrieve_token_status,
)


oauth_router = APIRouter()


def _resolve_environment(environment=None):
    if environment is None:
        return get_square_environment_name()

    normalized = environment.strip().lower()
    if normalized not in {"sandbox", "production"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid environment. Use 'sandbox' or 'production'.",
        )
    return normalized


def _summarize_auth_record(auth_record):
    if not auth_record:
        return None

    return {
        "source": auth_record["source"],
        "token_type": auth_record["token_type"],
        "expires_at": auth_record["expires_at"],
        "short_lived": auth_record["short_lived"],
        "scopes": auth_record["scopes"],
        "has_refresh_token": bool(auth_record["refresh_token"]),
        "updated_at": auth_record["updated_at"],
    }


# -- Onboarding UI ----------------------------------------------------------

_DISPLAY_TZ = ZoneInfo("America/Los_Angeles")


def _format_display_time(value):
    """Render a UTC timestamp as a human-readable Pacific-time string.

    Accepts a ``datetime`` or an ISO-8601 string (Square returns ``"...Z"``).
    Falls back to the raw value if parsing fails so the page never blows up on
    an unexpected format.
    """
    if value is None or value == "":
        return "unknown"
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_DISPLAY_TZ)
    # e.g. "Jun 2, 2026 at 7:42 AM PDT"
    return local.strftime("%b %-d, %Y at %-I:%M %p %Z")

_PAGE_STYLE = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       max-width: 540px; margin: 60px auto; padding: 0 20px; color: #1a1a1a; }
.brand { font-size: 13px; color: #666; padding-bottom: 12px;
         border-bottom: 1px solid #eee; margin-bottom: 32px; letter-spacing: 0.02em; }
h1 { font-size: 22px; margin: 0 0 16px 0; font-weight: 600; }
p { line-height: 1.55; color: #333; }
form { margin-top: 20px; }
.field-label { font-size: 13px; font-weight: 500; margin-bottom: 6px; color: #444; }
input[type=password], input[type=text] { width: 100%; padding: 10px 12px;
       font-size: 14px; border: 1px solid #ccc; border-radius: 6px;
       font-family: inherit; box-sizing: border-box; }
.btn { display: inline-block; background: #1a1a1a; color: white;
       padding: 10px 18px; border-radius: 6px; text-decoration: none;
       font-weight: 500; border: none; cursor: pointer; font-size: 14px;
       margin-top: 14px; font-family: inherit; }
.btn:hover { background: #333; }
.error { background: #fdf0f0; border: 1px solid #f5c2c0; color: #9b2c2c;
         padding: 10px 14px; border-radius: 6px; margin: 16px 0; font-size: 14px; }
.success-mark { color: #137333; font-weight: 600; }
.muted { color: #666; font-size: 13px; margin-top: 24px; }
.kv { margin: 12px 0; }
.kv dt { font-size: 12px; color: #666; text-transform: uppercase;
         letter-spacing: 0.04em; margin-top: 10px; }
.kv dd { margin: 2px 0 0 0; font-size: 14px; color: #1a1a1a; }
ul.scopes { margin: 4px 0 0 18px; padding: 0; color: #444; font-size: 14px; }
"""


def _render_page(title, body_html, *, status_code=200):
    return HTMLResponse(
        status_code=status_code,
        content=(
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{escape(title)} — Mosa Tea Inventory</title>"
            f"<style>{_PAGE_STYLE}</style></head><body>"
            "<div class='brand'>Mosa Tea Inventory</div>"
            f"<h1>{escape(title)}</h1>"
            f"{body_html}"
            "</body></html>"
        ),
    )


def _render_onboarding_gate(*, error=None, status_code=200):
    error_html = (
        f"<div class='error'>⚠ {escape(error)}</div>" if error else ""
    )
    body = (
        "<p>Paste the operator token to begin Square onboarding. "
        "The token is in your shared password manager.</p>"
        f"{error_html}"
        "<form method='post' action='/onboarding'>"
        "<div class='field-label'>Operator token</div>"
        "<input type='password' name='op_token' autocomplete='off' autofocus required />"
        "<br><button class='btn' type='submit'>Continue →</button>"
        "</form>"
    )
    return _render_page("Operator access required", body, status_code=status_code)


def _render_onboarding_connect():
    body = (
        "<p>Before continuing, sign in to Mosa Tea's Square seller account "
        "in this browser (a separate tab is fine). The next page will be on "
        "Square's site — the URL bar will show <code>squareup.com</code>.</p>"
        "<p><a class='btn' href='/oauth/square/start'>Connect to Square →</a></p>"
        "<p class='muted'>Your operator session expires automatically in ~2 hours.</p>"
    )
    return _render_page("Connect Mosa Tea to Square", body)


def _render_oauth_success(*, merchant_context, scopes, expires_at, connected_at):
    scope_items = "".join(f"<li>{escape(s)}</li>" for s in (scopes or [])) or "<li>none</li>"
    body = (
        "<p class='success-mark'>✓ Access granted.</p>"
        "<p>This automation now has API access to your Square account. "
        "It can read incoming orders and adjust inventory counts on your behalf — "
        "confirm the merchant below matches your shop.</p>"
        "<dl class='kv'>"
        f"<dt>Merchant</dt><dd>{escape(merchant_context.display_name or merchant_context.merchant_id)}</dd>"
        f"<dt>Merchant id</dt><dd><code>{escape(merchant_context.merchant_id)}</code></dd>"
        f"<dt>Environment</dt><dd>{escape(merchant_context.environment)}</dd>"
        f"<dt>Connected at</dt><dd>{escape(_format_display_time(connected_at))}</dd>"
        f"<dt>Token expires at</dt><dd>{escape(_format_display_time(expires_at))}</dd>"
        "<dt>Permissions granted</dt>"
        f"<dd><ul class='scopes'>{scope_items}</ul></dd>"
        "</dl>"
        "<p class='muted'>You can close this tab. Orders will be processed automatically from here.</p>"
    )
    return _render_page("Connected", body)


def _render_oauth_error(title, message, *, retry_label="Start over →", retry_href="/onboarding", status_code=400, reference=None):
    reference_html = (
        f"<p class='muted'>Reference: <code>{escape(reference)}</code></p>"
        if reference else ""
    )
    body = (
        f"<p>{escape(message)}</p>"
        f"{reference_html}"
        f"<p><a class='btn' href='{escape(retry_href)}'>{escape(retry_label)}</a></p>"
    )
    return _render_page(title, body, status_code=status_code)


def _verify_operator_session(request):
    """Return True if the request carries a valid operator session cookie."""
    return verify_session_value(request.cookies.get(OPERATOR_SESSION_COOKIE)) is not None


@oauth_router.get("/onboarding")
async def onboarding_page(request: Request):
    if _verify_operator_session(request):
        return _render_onboarding_connect()
    return _render_onboarding_gate()


@oauth_router.post("/onboarding")
async def onboarding_submit(op_token: str = Form(...)):
    try:
        expected = get_operator_api_token()
    except ValueError:
        return _render_oauth_error(
            "Configuration error",
            "The operator token isn't configured on the server. Contact the developer.",
            status_code=503,
        )

    if not compare_digest(op_token.strip(), expected):
        return _render_onboarding_gate(
            error="The token didn't match. Try again.",
            status_code=401,
        )

    now = int(time.time())
    value, expires_at = issue_session_value(now=now)
    response = RedirectResponse(url="/onboarding", status_code=303)
    set_session_cookie(response, value, max_age=max(expires_at - now, 1))
    return response


@oauth_router.get("/oauth/square/start")
async def square_oauth_start(
    request: Request,
    environment: str | None = Query(default=None),
):
    # Gate the browser flow behind the operator session cookie. CLI callers
    # that want to initiate OAuth programmatically should use the token-gated
    # routes (/status, /refresh) instead.
    if not _verify_operator_session(request):
        return RedirectResponse(url="/onboarding", status_code=303)

    resolved_environment = _resolve_environment(environment)
    state = create_oauth_state(resolved_environment)
    authorization_url = build_square_oauth_authorization_url(
        resolved_environment,
        state,
    )
    return RedirectResponse(url=authorization_url, status_code=302)


@oauth_router.get("/oauth/square/callback")
async def square_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    # 1. operator session cookie still valid?
    if not _verify_operator_session(request):
        return _render_oauth_error(
            "Operator session expired",
            "Your authenticated session ended before the Square flow completed "
            "(sessions last about 2 hours).",
            retry_label="Start over →",
            retry_href="/onboarding",
        )

    # 2. Square reported an error (most commonly access_denied = clicked Deny)
    if error:
        if error == "access_denied":
            return _render_oauth_error(
                "Connection cancelled",
                "You clicked Deny on Square's consent screen. Nothing was connected.",
                retry_label="Try again →",
                retry_href="/onboarding",
            )
        return _render_oauth_error(
            "Authorization failed",
            f"Square returned an error: {error_description or error}",
            retry_label="Start over →",
            retry_href="/onboarding",
        )

    # 3. basic protocol sanity
    if not code or not state:
        return _render_oauth_error(
            "Authorization expired",
            "The OAuth response was missing required parameters. This usually "
            "means the flow was interrupted — please restart.",
            retry_label="Start over →",
            retry_href="/onboarding",
        )

    # 4-5. state must exist + be tied to a recent flow (the consume_oauth_state
    # call atomically validates + expires + single-uses it).
    state_record = consume_oauth_state(state)
    if not state_record:
        return _render_oauth_error(
            "Authorization expired",
            "This OAuth flow took longer than its 5-minute window, was already "
            "used, or didn't match a request from this session.",
            retry_label="Start over →",
            retry_href="/onboarding",
        )

    # 6. exchange the code with Square — final source of truth
    environment = state_record["environment"]
    try:
        token_response = exchange_authorization_code(environment, code)
    except ApiError as error_response:
        return _render_oauth_error(
            "Couldn't complete the connection",
            "Square accepted the authorization but the token exchange failed. "
            "This is usually a transient network issue.",
            retry_label="Try again →",
            retry_href="/onboarding",
            reference=str(error_response)[:120],
        )

    if not token_response.access_token or not token_response.merchant_id:
        return _render_oauth_error(
            "Couldn't complete the connection",
            "Square didn't return an access token and merchant id. Try again.",
            retry_label="Try again →",
            retry_href="/onboarding",
        )

    try:
        token_status = retrieve_token_status(environment, token_response.access_token)
        locations = list_locations_for_merchant(environment, token_response.access_token)
    except ApiError as error_response:
        return _render_oauth_error(
            "Couldn't validate the connection",
            "Token exchange succeeded but follow-up validation failed.",
            retry_label="Try again →",
            retry_href="/onboarding",
            reference=str(error_response)[:120],
        )

    selected_location_id = choose_default_location_id(locations)
    merchant_context = upsert_oauth_merchant(
        environment,
        token_response.merchant_id,
        token_response.access_token,
        refresh_token=token_response.refresh_token,
        selected_location_id=selected_location_id,
        display_name=(
            next(
                (
                    getattr(location, "business_name", None)
                    or getattr(location, "name", None)
                    for location in locations
                    if getattr(location, "id", None) == selected_location_id
                ),
                None,
            )
        ),
        token_type=token_response.token_type,
        expires_at=token_response.expires_at or token_status.expires_at,
        short_lived=token_response.short_lived,
        scopes=token_status.scopes,
    )

    return _render_oauth_success(
        merchant_context=merchant_context,
        scopes=token_status.scopes,
        expires_at=token_status.expires_at,
        connected_at=datetime.now(timezone.utc),
    )


@oauth_router.get("/oauth/square/status", dependencies=[Depends(require_operator_access)])
async def square_oauth_status():
    contexts = list_merchant_contexts()
    return {
        "merchants": [
            {
                "environment": context.environment,
                "merchant_id": context.merchant_id,
                "status": context.status,
                "auth_mode": context.auth_mode,
                "display_name": context.display_name,
                "selected_location_id": context.location_id,
                "writes_enabled": context.writes_enabled,
                "binding_version": context.binding_version,
                "write_ready": readiness["write_ready"],
                "write_blockers": readiness["write_blockers"],
                "auth": _summarize_auth_record(
                    get_merchant_auth_record(
                        context.environment,
                        context.merchant_id,
                    )
                ),
            }
            for context in contexts
            for readiness in [
                get_merchant_write_readiness(
                    context.environment,
                    context.merchant_id,
                )
            ]
        ]
    }


@oauth_router.post(
    "/oauth/square/refresh/{merchant_id}",
    dependencies=[Depends(require_operator_access)],
)
async def square_oauth_refresh(
    merchant_id: str,
    environment: str | None = Query(default=None),
):
    resolved_environment = _resolve_environment(environment)

    try:
        auth_record = refresh_oauth_merchant_access_token(
            resolved_environment,
            merchant_id,
            force=True,
        )
    except ValueError as error_response:
        raise HTTPException(status_code=400, detail=str(error_response)) from error_response
    except ApiError as error_response:
        return JSONResponse(
            status_code=400,
            content={
                "error": "oauth_token_refresh_failed",
                "detail": str(error_response),
            },
        )

    token_status = retrieve_token_status(
        resolved_environment,
        auth_record["access_token"],
    )
    return {
        "refreshed": True,
        "merchant_id": merchant_id,
        "environment": resolved_environment,
        "auth": _summarize_auth_record(auth_record),
        "token_status": {
            "merchant_id": token_status.merchant_id,
            "client_id": token_status.client_id,
            "expires_at": token_status.expires_at,
            "scopes": token_status.scopes,
        },
    }
