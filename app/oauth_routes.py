from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from square.core.api_error import ApiError

from app.config import get_square_environment_name
from app.merchant_store import (
    get_merchant_auth_record,
    list_merchant_contexts,
    refresh_oauth_merchant_access_token,
    upsert_oauth_merchant,
)
from app.oauth_state_db import consume_oauth_state, create_oauth_state
from app.operator_auth import require_operator_access
from app.square_oauth import (
    build_square_oauth_authorization_url,
    choose_default_location_id,
    exchange_authorization_code,
    list_locations_for_merchant,
    retrieve_token_status,
    summarize_location,
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


def _render_oauth_page(title, lines, *, status_code=200):
    escaped_title = escape(str(title))
    line_html = "".join(f"<li>{escape(str(line))}</li>" for line in lines)
    return HTMLResponse(
        status_code=status_code,
        content=(
            "<!doctype html>"
            "<html><head><meta charset='utf-8'><title>"
            f"{escaped_title}"
            "</title></head><body style='font-family: sans-serif; max-width: 720px; margin: 40px auto;'>"
            f"<h1>{escaped_title}</h1>"
            f"<ul>{line_html}</ul>"
            "</body></html>"
        ),
    )


@oauth_router.get("/oauth/square/start", dependencies=[Depends(require_operator_access)])
async def square_oauth_start(environment: str | None = Query(default=None)):
    resolved_environment = _resolve_environment(environment)
    state = create_oauth_state(resolved_environment)
    authorization_url = build_square_oauth_authorization_url(
        resolved_environment,
        state,
    )
    return RedirectResponse(url=authorization_url, status_code=302)


@oauth_router.get("/oauth/square/callback")
async def square_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if error:
        return _render_oauth_page(
            "Square OAuth Error",
            [
                f"error: {error}",
                f"error_description: {error_description or 'none'}",
            ],
            status_code=400,
        )

    if not code or not state:
        return _render_oauth_page(
            "Square OAuth Error",
            ["OAuth callback requires both code and state."],
            status_code=400,
        )

    state_record = consume_oauth_state(state)
    if not state_record:
        return _render_oauth_page(
            "Square OAuth Error",
            ["Invalid or expired OAuth state."],
            status_code=400,
        )

    environment = state_record["environment"]
    try:
        token_response = exchange_authorization_code(environment, code)
    except ApiError as error_response:
        return _render_oauth_page(
            "Square OAuth Error",
            [
                "oauth_token_exchange_failed",
                str(error_response),
            ],
            status_code=400,
        )

    if not token_response.access_token or not token_response.merchant_id:
        return _render_oauth_page(
            "Square OAuth Error",
            [
                "oauth_token_exchange_failed",
                "Square did not return an access token and merchant_id.",
            ],
            status_code=400,
        )

    try:
        token_status = retrieve_token_status(environment, token_response.access_token)
        locations = list_locations_for_merchant(environment, token_response.access_token)
    except ApiError as error_response:
        return _render_oauth_page(
            "Square OAuth Error",
            [
                "oauth_post_connect_validation_failed",
                str(error_response),
            ],
            status_code=400,
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
        writes_enabled=False,
    )

    return _render_oauth_page(
        "Square OAuth Connected",
        [
            f"merchant_id: {merchant_context.merchant_id}",
            f"environment: {merchant_context.environment}",
            f"display_name: {merchant_context.display_name or 'unknown'}",
            f"selected_location_id: {merchant_context.location_id or 'none'}",
            f"writes_enabled: {merchant_context.writes_enabled}",
            f"expires_at: {token_status.expires_at}",
            f"scopes: {', '.join(token_status.scopes or []) or 'none'}",
            f"location_count: {len(locations)}",
        ],
        status_code=200,
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
                "auth": _summarize_auth_record(
                    get_merchant_auth_record(
                        context.environment,
                        context.merchant_id,
                    )
                ),
            }
            for context in contexts
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
