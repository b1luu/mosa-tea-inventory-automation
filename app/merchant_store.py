from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.config import get_merchant_store_mode
from app import merchant_store_db, merchant_store_dynamodb
from app.merchant_store_constants import (
    AUTH_SOURCE_MANUAL_TOKEN,
    AUTH_SOURCE_OAUTH,
    BINDING_STATUS_APPROVED,
    BINDING_STATUS_DRAFT,
    MERCHANT_STATUS_ACTIVE,
    MERCHANT_STATUS_DISABLED,
    MERCHANT_STATUS_REVOKED,
)
from app.square_oauth import refresh_authorization_token


@dataclass(frozen=True)
class MerchantContext:
    environment: str
    merchant_id: str
    status: str
    auth_mode: str
    location_id: str | None
    writes_enabled: bool
    binding_version: int | None
    display_name: str | None = None


def _utcnow():
    return datetime.now(UTC).isoformat()


def _parse_datetime(value):
    if not value:
        return None

    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _oauth_token_needs_refresh(expires_at, *, refresh_window_seconds=300):
    expires_at_dt = _parse_datetime(expires_at)
    if expires_at_dt is None:
        return False

    return expires_at_dt <= datetime.now(UTC) + timedelta(seconds=refresh_window_seconds)


def _get_store_backend():
    store_mode = get_merchant_store_mode()
    if store_mode == "sqlite":
        return merchant_store_db
    if store_mode == "dynamodb":
        return merchant_store_dynamodb
    raise ValueError(f"Unsupported merchant store mode: {store_mode}")


def get_merchant_context(environment, merchant_id):
    connection = _get_store_backend().get_merchant_connection(environment, merchant_id)
    if not connection:
        return None

    return MerchantContext(
        environment=connection["environment"],
        merchant_id=connection["merchant_id"],
        status=connection["status"],
        auth_mode=connection["auth_mode"],
        location_id=connection["selected_location_id"],
        writes_enabled=connection["writes_enabled"],
        binding_version=connection["active_binding_version"],
        display_name=connection["display_name"],
    )


def list_merchant_contexts(status=None):
    return [
        MerchantContext(
            environment=connection["environment"],
            merchant_id=connection["merchant_id"],
            status=connection["status"],
            auth_mode=connection["auth_mode"],
            location_id=connection["selected_location_id"],
            writes_enabled=connection["writes_enabled"],
            binding_version=connection["active_binding_version"],
            display_name=connection["display_name"],
        )
        for connection in _get_store_backend().list_merchant_connections(status=status)
    ]


def get_merchant_access_token(environment, merchant_id):
    return _get_store_backend().get_merchant_access_token(environment, merchant_id)


def get_merchant_auth_record(environment, merchant_id):
    return _get_store_backend().get_merchant_auth(environment, merchant_id)


def refresh_oauth_merchant_access_token(
    environment,
    merchant_id,
    *,
    force=False,
    refresh_window_seconds=300,
):
    backend = _get_store_backend()
    auth_record = get_merchant_auth_record(environment, merchant_id)
    if not auth_record:
        raise ValueError(
            f"No Square auth record found for merchant {merchant_id!r} "
            f"in environment {environment!r}."
        )

    if auth_record["source"] != AUTH_SOURCE_OAUTH:
        raise ValueError(
            f"Merchant {merchant_id!r} in environment {environment!r} is not using OAuth."
        )

    if not auth_record["refresh_token"]:
        raise ValueError(
            f"Merchant {merchant_id!r} in environment {environment!r} has no refresh token."
        )

    if not force and not _oauth_token_needs_refresh(
        auth_record["expires_at"],
        refresh_window_seconds=refresh_window_seconds,
    ):
        return auth_record

    token_response = refresh_authorization_token(
        environment,
        auth_record["refresh_token"],
    )

    response_merchant_id = getattr(token_response, "merchant_id", None)
    if response_merchant_id and response_merchant_id != merchant_id:
        raise ValueError(
            "Square returned a refreshed token for a different merchant than expected."
        )

    backend.upsert_merchant_auth(
        environment,
        merchant_id,
        token_response.access_token,
        refresh_token=(
            getattr(token_response, "refresh_token", None) or auth_record["refresh_token"]
        ),
        token_type=getattr(token_response, "token_type", None) or auth_record["token_type"],
        expires_at=getattr(token_response, "expires_at", None) or auth_record["expires_at"],
        short_lived=(
            getattr(token_response, "short_lived", None)
            if getattr(token_response, "short_lived", None) is not None
            else auth_record["short_lived"]
        ),
        scopes=auth_record["scopes"],
        source=AUTH_SOURCE_OAUTH,
    )
    return get_merchant_auth_record(environment, merchant_id)


def resolve_merchant_access_token(
    environment,
    merchant_id,
    *,
    refresh_if_needed=True,
    refresh_window_seconds=300,
):
    auth_record = get_merchant_auth_record(environment, merchant_id)
    if not auth_record:
        return None

    if (
        refresh_if_needed
        and auth_record["source"] == AUTH_SOURCE_OAUTH
        and auth_record["refresh_token"]
    ):
        auth_record = refresh_oauth_merchant_access_token(
            environment,
            merchant_id,
            force=False,
            refresh_window_seconds=refresh_window_seconds,
        )

    return auth_record["access_token"]


def get_active_catalog_binding(environment, merchant_id, location_id):
    return _get_store_backend().get_active_catalog_binding(
        environment,
        merchant_id,
        location_id,
    )


def list_catalog_bindings(environment, merchant_id, *, location_id=None, status=None):
    return _get_store_backend().list_merchant_catalog_bindings(
        environment,
        merchant_id,
        location_id=location_id,
        status=status,
    )


def get_merchant_write_readiness(environment, merchant_id):
    merchant_context = get_merchant_context(environment, merchant_id)
    auth_record = get_merchant_auth_record(environment, merchant_id)
    location_id = merchant_context.location_id if merchant_context else None
    active_binding = (
        get_active_catalog_binding(environment, merchant_id, location_id)
        if location_id
        else None
    )

    reasons = []
    if merchant_context is None:
        reasons.append("merchant_not_found")
    else:
        if merchant_context.status != MERCHANT_STATUS_ACTIVE:
            reasons.append(f"merchant_status_{merchant_context.status}")
        if not merchant_context.location_id:
            reasons.append("missing_selected_location")

    if auth_record is None:
        reasons.append("missing_auth_record")
    if active_binding is None:
        reasons.append("missing_approved_binding")

    return {
        "merchant_context": merchant_context,
        "auth_record": auth_record,
        "active_binding": active_binding,
        "ready": not reasons,
        "reasons": reasons,
    }


def upsert_manual_merchant(
    environment,
    merchant_id,
    access_token,
    *,
    selected_location_id=None,
    display_name=None,
    scopes=None,
    writes_enabled=False,
    status=MERCHANT_STATUS_ACTIVE,
):
    backend = _get_store_backend()
    backend.upsert_merchant_connection(
        environment,
        merchant_id,
        status=status,
        auth_mode=AUTH_SOURCE_MANUAL_TOKEN,
        display_name=display_name,
        selected_location_id=selected_location_id,
        writes_enabled=writes_enabled,
    )
    backend.upsert_merchant_auth(
        environment,
        merchant_id,
        access_token,
        scopes=scopes,
        source=AUTH_SOURCE_MANUAL_TOKEN,
    )
    return get_merchant_context(environment, merchant_id)


def upsert_oauth_merchant(
    environment,
    merchant_id,
    access_token,
    *,
    refresh_token,
    selected_location_id=None,
    display_name=None,
    token_type=None,
    expires_at=None,
    short_lived=None,
    scopes=None,
    writes_enabled=False,
    status=MERCHANT_STATUS_ACTIVE,
):
    backend = _get_store_backend()
    backend.upsert_merchant_connection(
        environment,
        merchant_id,
        status=status,
        auth_mode=AUTH_SOURCE_OAUTH,
        display_name=display_name,
        selected_location_id=selected_location_id,
        writes_enabled=writes_enabled,
    )
    backend.upsert_merchant_auth(
        environment,
        merchant_id,
        access_token,
        refresh_token=refresh_token,
        token_type=token_type,
        expires_at=expires_at,
        short_lived=short_lived,
        scopes=scopes,
        source=AUTH_SOURCE_OAUTH,
    )
    return get_merchant_context(environment, merchant_id)


def set_selected_location_id(environment, merchant_id, selected_location_id):
    return _get_store_backend().set_selected_location_id(
        environment,
        merchant_id,
        selected_location_id,
    )


def enable_merchant_writes(environment, merchant_id):
    return _get_store_backend().set_writes_enabled(environment, merchant_id, True)


def disable_merchant_writes(environment, merchant_id):
    return _get_store_backend().set_writes_enabled(environment, merchant_id, False)


def revoke_merchant(environment, merchant_id):
    return _get_store_backend().set_merchant_connection_status(
        environment,
        merchant_id,
        MERCHANT_STATUS_REVOKED,
    )


def disable_merchant(environment, merchant_id):
    return _get_store_backend().set_merchant_connection_status(
        environment,
        merchant_id,
        MERCHANT_STATUS_DISABLED,
    )


def upsert_catalog_binding(
    environment,
    merchant_id,
    location_id,
    version,
    mapping,
    *,
    status=BINDING_STATUS_DRAFT,
    notes=None,
):
    backend = _get_store_backend()
    approved_at = _utcnow() if status == BINDING_STATUS_APPROVED else None
    backend.upsert_merchant_catalog_binding(
        environment,
        merchant_id,
        location_id,
        version,
        mapping,
        status=status,
        notes=notes,
        approved_at=approved_at,
    )
    if status == BINDING_STATUS_APPROVED:
        backend.set_active_binding_version(
            environment,
            merchant_id,
            version,
        )
    return backend.get_merchant_catalog_binding(
        environment,
        merchant_id,
        location_id,
        version,
    )


def approve_catalog_binding(environment, merchant_id, location_id, version):
    backend = _get_store_backend()
    approved_at = _utcnow()
    updated = backend.set_catalog_binding_status(
        environment,
        merchant_id,
        location_id,
        version,
        BINDING_STATUS_APPROVED,
        approved_at=approved_at,
    )
    if not updated:
        return False

    backend.set_active_binding_version(
        environment,
        merchant_id,
        version,
    )
    return True


def enable_merchant_writes_if_ready(environment, merchant_id):
    backend = _get_store_backend()
    readiness = get_merchant_write_readiness(environment, merchant_id)
    if not readiness["ready"]:
        return {
            "enabled": False,
            "readiness": readiness,
        }

    enabled = backend.set_writes_enabled(environment, merchant_id, True)
    return {
        "enabled": enabled,
        "readiness": get_merchant_write_readiness(environment, merchant_id),
    }
