import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


DB_FILE = Path("data/merchant_store.db")

MERCHANT_STATUS_PENDING = "pending"
MERCHANT_STATUS_ACTIVE = "active"
MERCHANT_STATUS_REVOKED = "revoked"
MERCHANT_STATUS_DISABLED = "disabled"

AUTH_SOURCE_MANUAL_TOKEN = "manual_token"
AUTH_SOURCE_OAUTH = "oauth"

BINDING_STATUS_DRAFT = "draft"
BINDING_STATUS_APPROVED = "approved"
BINDING_STATUS_ARCHIVED = "archived"


def _utcnow():
    return datetime.now(UTC).isoformat()


def _serialize_json(value):
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _deserialize_json(value):
    if value is None:
        return None
    return json.loads(value)


def ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS merchant_connection (
                environment TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                status TEXT NOT NULL,
                auth_mode TEXT NOT NULL,
                display_name TEXT,
                selected_location_id TEXT,
                writes_enabled INTEGER NOT NULL DEFAULT 0,
                active_binding_version INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (environment, merchant_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS merchant_auth (
                environment TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_type TEXT,
                expires_at TEXT,
                short_lived INTEGER,
                scopes_json TEXT,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (environment, merchant_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS merchant_catalog_binding (
                environment TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                location_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                mapping_json TEXT NOT NULL,
                notes TEXT,
                approved_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (environment, merchant_id, location_id, version)
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_merchant_catalog_binding_status
            ON merchant_catalog_binding (
                environment,
                merchant_id,
                location_id,
                status,
                version DESC
            )
            """
        )


def upsert_merchant_connection(
    environment,
    merchant_id,
    *,
    status,
    auth_mode,
    display_name=None,
    selected_location_id=None,
    writes_enabled=False,
    active_binding_version=None,
):
    ensure_db()
    now = _utcnow()
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO merchant_connection (
                environment,
                merchant_id,
                status,
                auth_mode,
                display_name,
                selected_location_id,
                writes_enabled,
                active_binding_version,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(environment, merchant_id) DO UPDATE SET
                status = excluded.status,
                auth_mode = excluded.auth_mode,
                display_name = excluded.display_name,
                selected_location_id = excluded.selected_location_id,
                writes_enabled = excluded.writes_enabled,
                active_binding_version = excluded.active_binding_version,
                updated_at = excluded.updated_at
            """,
            (
                environment,
                merchant_id,
                status,
                auth_mode,
                display_name,
                selected_location_id,
                int(bool(writes_enabled)),
                active_binding_version,
                now,
                now,
            ),
        )


def get_merchant_connection(environment, merchant_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT
                environment,
                merchant_id,
                status,
                auth_mode,
                display_name,
                selected_location_id,
                writes_enabled,
                active_binding_version,
                created_at,
                updated_at
            FROM merchant_connection
            WHERE environment = ? AND merchant_id = ?
            """,
            (environment, merchant_id),
        ).fetchone()

    if not row:
        return None

    return {
        "environment": row[0],
        "merchant_id": row[1],
        "status": row[2],
        "auth_mode": row[3],
        "display_name": row[4],
        "selected_location_id": row[5],
        "writes_enabled": bool(row[6]),
        "active_binding_version": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def list_merchant_connections(status=None):
    ensure_db()
    query = (
        "SELECT environment, merchant_id, status, auth_mode, display_name, "
        "selected_location_id, writes_enabled, active_binding_version, created_at, updated_at "
        "FROM merchant_connection"
    )
    params = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY updated_at DESC"

    with sqlite3.connect(DB_FILE) as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        {
            "environment": row[0],
            "merchant_id": row[1],
            "status": row[2],
            "auth_mode": row[3],
            "display_name": row[4],
            "selected_location_id": row[5],
            "writes_enabled": bool(row[6]),
            "active_binding_version": row[7],
            "created_at": row[8],
            "updated_at": row[9],
        }
        for row in rows
    ]


def set_merchant_connection_status(environment, merchant_id, status):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            """
            UPDATE merchant_connection
            SET status = ?, updated_at = ?
            WHERE environment = ? AND merchant_id = ?
            """,
            (status, _utcnow(), environment, merchant_id),
        )

    return cursor.rowcount == 1


def set_selected_location_id(environment, merchant_id, selected_location_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            """
            UPDATE merchant_connection
            SET selected_location_id = ?, updated_at = ?
            WHERE environment = ? AND merchant_id = ?
            """,
            (selected_location_id, _utcnow(), environment, merchant_id),
        )

    return cursor.rowcount == 1


def set_writes_enabled(environment, merchant_id, writes_enabled):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            """
            UPDATE merchant_connection
            SET writes_enabled = ?, updated_at = ?
            WHERE environment = ? AND merchant_id = ?
            """,
            (int(bool(writes_enabled)), _utcnow(), environment, merchant_id),
        )

    return cursor.rowcount == 1


def set_active_binding_version(environment, merchant_id, active_binding_version):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            """
            UPDATE merchant_connection
            SET active_binding_version = ?, updated_at = ?
            WHERE environment = ? AND merchant_id = ?
            """,
            (active_binding_version, _utcnow(), environment, merchant_id),
        )

    return cursor.rowcount == 1


def upsert_merchant_auth(
    environment,
    merchant_id,
    access_token,
    *,
    refresh_token=None,
    token_type=None,
    expires_at=None,
    short_lived=None,
    scopes=None,
    source,
):
    ensure_db()
    now = _utcnow()
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO merchant_auth (
                environment,
                merchant_id,
                access_token,
                refresh_token,
                token_type,
                expires_at,
                short_lived,
                scopes_json,
                source,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(environment, merchant_id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                token_type = excluded.token_type,
                expires_at = excluded.expires_at,
                short_lived = excluded.short_lived,
                scopes_json = excluded.scopes_json,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (
                environment,
                merchant_id,
                access_token,
                refresh_token,
                token_type,
                expires_at,
                int(short_lived) if short_lived is not None else None,
                _serialize_json(list(scopes) if scopes is not None else None),
                source,
                now,
                now,
            ),
        )


def get_merchant_auth(environment, merchant_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT
                environment,
                merchant_id,
                access_token,
                refresh_token,
                token_type,
                expires_at,
                short_lived,
                scopes_json,
                source,
                created_at,
                updated_at
            FROM merchant_auth
            WHERE environment = ? AND merchant_id = ?
            """,
            (environment, merchant_id),
        ).fetchone()

    if not row:
        return None

    return {
        "environment": row[0],
        "merchant_id": row[1],
        "access_token": row[2],
        "refresh_token": row[3],
        "token_type": row[4],
        "expires_at": row[5],
        "short_lived": bool(row[6]) if row[6] is not None else None,
        "scopes": _deserialize_json(row[7]),
        "source": row[8],
        "created_at": row[9],
        "updated_at": row[10],
    }


def get_merchant_access_token(environment, merchant_id):
    record = get_merchant_auth(environment, merchant_id)
    if not record:
        return None
    return record["access_token"]


def upsert_merchant_catalog_binding(
    environment,
    merchant_id,
    location_id,
    version,
    mapping,
    *,
    status=BINDING_STATUS_DRAFT,
    notes=None,
    approved_at=None,
):
    ensure_db()
    now = _utcnow()
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO merchant_catalog_binding (
                environment,
                merchant_id,
                location_id,
                version,
                status,
                mapping_json,
                notes,
                approved_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(environment, merchant_id, location_id, version) DO UPDATE SET
                status = excluded.status,
                mapping_json = excluded.mapping_json,
                notes = excluded.notes,
                approved_at = excluded.approved_at,
                updated_at = excluded.updated_at
            """,
            (
                environment,
                merchant_id,
                location_id,
                version,
                status,
                _serialize_json(mapping),
                notes,
                approved_at,
                now,
                now,
            ),
        )


def get_merchant_catalog_binding(environment, merchant_id, location_id, version):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT
                environment,
                merchant_id,
                location_id,
                version,
                status,
                mapping_json,
                notes,
                approved_at,
                created_at,
                updated_at
            FROM merchant_catalog_binding
            WHERE environment = ? AND merchant_id = ? AND location_id = ? AND version = ?
            """,
            (environment, merchant_id, location_id, version),
        ).fetchone()

    if not row:
        return None

    return {
        "environment": row[0],
        "merchant_id": row[1],
        "location_id": row[2],
        "version": row[3],
        "status": row[4],
        "mapping": _deserialize_json(row[5]),
        "notes": row[6],
        "approved_at": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def get_active_catalog_binding(environment, merchant_id, location_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT
                environment,
                merchant_id,
                location_id,
                version,
                status,
                mapping_json,
                notes,
                approved_at,
                created_at,
                updated_at
            FROM merchant_catalog_binding
            WHERE environment = ? AND merchant_id = ? AND location_id = ? AND status = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (environment, merchant_id, location_id, BINDING_STATUS_APPROVED),
        ).fetchone()

    if not row:
        return None

    return {
        "environment": row[0],
        "merchant_id": row[1],
        "location_id": row[2],
        "version": row[3],
        "status": row[4],
        "mapping": _deserialize_json(row[5]),
        "notes": row[6],
        "approved_at": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def list_merchant_catalog_bindings(environment, merchant_id, location_id=None, status=None):
    ensure_db()
    query = (
        "SELECT environment, merchant_id, location_id, version, status, mapping_json, "
        "notes, approved_at, created_at, updated_at "
        "FROM merchant_catalog_binding WHERE environment = ? AND merchant_id = ?"
    )
    params = [environment, merchant_id]

    if location_id is not None:
        query += " AND location_id = ?"
        params.append(location_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY location_id ASC, version DESC"

    with sqlite3.connect(DB_FILE) as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    return [
        {
            "environment": row[0],
            "merchant_id": row[1],
            "location_id": row[2],
            "version": row[3],
            "status": row[4],
            "mapping": _deserialize_json(row[5]),
            "notes": row[6],
            "approved_at": row[7],
            "created_at": row[8],
            "updated_at": row[9],
        }
        for row in rows
    ]


def set_catalog_binding_status(
    environment,
    merchant_id,
    location_id,
    version,
    status,
    *,
    approved_at=None,
):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            """
            UPDATE merchant_catalog_binding
            SET status = ?, approved_at = ?, updated_at = ?
            WHERE environment = ? AND merchant_id = ? AND location_id = ? AND version = ?
            """,
            (
                status,
                approved_at,
                _utcnow(),
                environment,
                merchant_id,
                location_id,
                version,
            ),
        )

    return cursor.rowcount == 1
