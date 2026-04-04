from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from square.core.api_error import ApiError

from app.config import get_square_environment_name
from app.merchant_store import list_merchant_contexts, upsert_oauth_merchant
from app.oauth_state_db import consume_oauth_state, create_oauth_state
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


@oauth_router.get("/oauth/square/start")
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
        return JSONResponse(
            status_code=400,
            content={
                "error": error,
                "error_description": error_description,
            },
        )

    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="OAuth callback requires both 'code' and 'state'.",
        )

    state_record = consume_oauth_state(state)
    if not state_record:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")

    environment = state_record["environment"]
    try:
        token_response = exchange_authorization_code(environment, code)
    except ApiError as error_response:
        return JSONResponse(
            status_code=400,
            content={
                "error": "oauth_token_exchange_failed",
                "detail": str(error_response),
            },
        )

    if not token_response.access_token or not token_response.merchant_id:
        return JSONResponse(
            status_code=400,
            content={
                "error": "oauth_token_exchange_failed",
                "detail": "Square did not return an access token and merchant_id.",
            },
        )

    try:
        token_status = retrieve_token_status(environment, token_response.access_token)
        locations = list_locations_for_merchant(environment, token_response.access_token)
    except ApiError as error_response:
        return JSONResponse(
            status_code=400,
            content={
                "error": "oauth_post_connect_validation_failed",
                "detail": str(error_response),
            },
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

    return {
        "connected": True,
        "merchant": {
            "environment": merchant_context.environment,
            "merchant_id": merchant_context.merchant_id,
            "status": merchant_context.status,
            "auth_mode": merchant_context.auth_mode,
            "display_name": merchant_context.display_name,
            "selected_location_id": merchant_context.location_id,
            "writes_enabled": merchant_context.writes_enabled,
        },
        "token_status": {
            "merchant_id": token_status.merchant_id,
            "client_id": token_status.client_id,
            "expires_at": token_status.expires_at,
            "scopes": token_status.scopes,
        },
        "locations": [summarize_location(location) for location in locations],
    }


@oauth_router.get("/oauth/square/status")
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
            }
            for context in contexts
        ]
    }
