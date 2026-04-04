from dataclasses import dataclass
from datetime import UTC, datetime

from app import merchant_store_db


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


def get_merchant_context(environment, merchant_id):
    connection = merchant_store_db.get_merchant_connection(environment, merchant_id)
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
        for connection in merchant_store_db.list_merchant_connections(status=status)
    ]


def get_merchant_access_token(environment, merchant_id):
    return merchant_store_db.get_merchant_access_token(environment, merchant_id)


def get_active_catalog_binding(environment, merchant_id, location_id):
    return merchant_store_db.get_active_catalog_binding(
        environment,
        merchant_id,
        location_id,
    )


def upsert_manual_merchant(
    environment,
    merchant_id,
    access_token,
    *,
    selected_location_id=None,
    display_name=None,
    scopes=None,
    writes_enabled=False,
    status=merchant_store_db.MERCHANT_STATUS_ACTIVE,
):
    merchant_store_db.upsert_merchant_connection(
        environment,
        merchant_id,
        status=status,
        auth_mode=merchant_store_db.AUTH_SOURCE_MANUAL_TOKEN,
        display_name=display_name,
        selected_location_id=selected_location_id,
        writes_enabled=writes_enabled,
    )
    merchant_store_db.upsert_merchant_auth(
        environment,
        merchant_id,
        access_token,
        scopes=scopes,
        source=merchant_store_db.AUTH_SOURCE_MANUAL_TOKEN,
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
    status=merchant_store_db.MERCHANT_STATUS_ACTIVE,
):
    merchant_store_db.upsert_merchant_connection(
        environment,
        merchant_id,
        status=status,
        auth_mode=merchant_store_db.AUTH_SOURCE_OAUTH,
        display_name=display_name,
        selected_location_id=selected_location_id,
        writes_enabled=writes_enabled,
    )
    merchant_store_db.upsert_merchant_auth(
        environment,
        merchant_id,
        access_token,
        refresh_token=refresh_token,
        token_type=token_type,
        expires_at=expires_at,
        short_lived=short_lived,
        scopes=scopes,
        source=merchant_store_db.AUTH_SOURCE_OAUTH,
    )
    return get_merchant_context(environment, merchant_id)


def set_selected_location_id(environment, merchant_id, selected_location_id):
    return merchant_store_db.set_selected_location_id(
        environment,
        merchant_id,
        selected_location_id,
    )


def enable_merchant_writes(environment, merchant_id):
    return merchant_store_db.set_writes_enabled(environment, merchant_id, True)


def disable_merchant_writes(environment, merchant_id):
    return merchant_store_db.set_writes_enabled(environment, merchant_id, False)


def revoke_merchant(environment, merchant_id):
    return merchant_store_db.set_merchant_connection_status(
        environment,
        merchant_id,
        merchant_store_db.MERCHANT_STATUS_REVOKED,
    )


def disable_merchant(environment, merchant_id):
    return merchant_store_db.set_merchant_connection_status(
        environment,
        merchant_id,
        merchant_store_db.MERCHANT_STATUS_DISABLED,
    )


def upsert_catalog_binding(
    environment,
    merchant_id,
    location_id,
    version,
    mapping,
    *,
    status=merchant_store_db.BINDING_STATUS_DRAFT,
    notes=None,
):
    approved_at = _utcnow() if status == merchant_store_db.BINDING_STATUS_APPROVED else None
    merchant_store_db.upsert_merchant_catalog_binding(
        environment,
        merchant_id,
        location_id,
        version,
        mapping,
        status=status,
        notes=notes,
        approved_at=approved_at,
    )
    if status == merchant_store_db.BINDING_STATUS_APPROVED:
        merchant_store_db.set_active_binding_version(
            environment,
            merchant_id,
            version,
        )
    return merchant_store_db.get_merchant_catalog_binding(
        environment,
        merchant_id,
        location_id,
        version,
    )


def approve_catalog_binding(environment, merchant_id, location_id, version):
    approved_at = _utcnow()
    updated = merchant_store_db.set_catalog_binding_status(
        environment,
        merchant_id,
        location_id,
        version,
        merchant_store_db.BINDING_STATUS_APPROVED,
        approved_at=approved_at,
    )
    if not updated:
        return False

    merchant_store_db.set_active_binding_version(
        environment,
        merchant_id,
        version,
    )
    return True
