import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


DB_FILE = Path("data/merchant_auth.db")
MERCHANT_STATUS_ACTIVE = "active"
MERCHANT_STATUS_REVOKED = "revoked"


def ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS merchant_auth (
                merchant_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                token_type TEXT,
                expires_at TEXT,
                short_lived INTEGER,
                scopes_json TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def _serialize_scopes(scopes):
    if scopes is None:
        return None
    return json.dumps(list(scopes))


def _deserialize_scopes(scopes_json):
    if scopes_json is None:
        return None
    return json.loads(scopes_json)


def upsert_merchant_auth_record(
    merchant_id,
    access_token,
    refresh_token,
    *,
    token_type=None,
    expires_at=None,
    short_lived=None,
    scopes=None,
    status=MERCHANT_STATUS_ACTIVE,
):
    ensure_db()
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO merchant_auth (
                merchant_id,
                access_token,
                refresh_token,
                token_type,
                expires_at,
                short_lived,
                scopes_json,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(merchant_id) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                token_type = excluded.token_type,
                expires_at = excluded.expires_at,
                short_lived = excluded.short_lived,
                scopes_json = excluded.scopes_json,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                merchant_id,
                access_token,
                refresh_token,
                token_type,
                expires_at,
                int(short_lived) if short_lived is not None else None,
                _serialize_scopes(scopes),
                status,
                now,
                now,
            ),
        )


def get_merchant_auth_record(merchant_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT
                merchant_id,
                access_token,
                refresh_token,
                token_type,
                expires_at,
                short_lived,
                scopes_json,
                status,
                created_at,
                updated_at
            FROM merchant_auth
            WHERE merchant_id = ?
            """,
            (merchant_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "merchant_id": row[0],
        "access_token": row[1],
        "refresh_token": row[2],
        "token_type": row[3],
        "expires_at": row[4],
        "short_lived": bool(row[5]) if row[5] is not None else None,
        "scopes": _deserialize_scopes(row[6]),
        "status": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def get_merchant_access_token(merchant_id):
    record = get_merchant_auth_record(merchant_id)
    if not record or record["status"] != MERCHANT_STATUS_ACTIVE:
        return None
    return record["access_token"]


def list_merchant_auth_records(status=None):
    ensure_db()
    query = (
        "SELECT merchant_id, token_type, expires_at, short_lived, "
        "scopes_json, status, created_at, updated_at "
        "FROM merchant_auth"
    )
    params = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY updated_at DESC"

    with sqlite3.connect(DB_FILE) as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        {
            "merchant_id": row[0],
            "token_type": row[1],
            "expires_at": row[2],
            "short_lived": bool(row[3]) if row[3] is not None else None,
            "scopes": _deserialize_scopes(row[4]),
            "status": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }
        for row in rows
    ]


def mark_merchant_auth_revoked(merchant_id):
    record = get_merchant_auth_record(merchant_id)
    if not record:
        return
    upsert_merchant_auth_record(
        merchant_id=merchant_id,
        access_token=record["access_token"],
        refresh_token=record["refresh_token"],
        token_type=record["token_type"],
        expires_at=record["expires_at"],
        short_lived=record["short_lived"],
        scopes=record["scopes"],
        status=MERCHANT_STATUS_REVOKED,
    )
