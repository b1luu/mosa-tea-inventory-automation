import sqlite3
from datetime import UTC, datetime
from pathlib import Path


DB_FILE = Path("data/webhook_events.db")
EVENT_STATUS_RECEIVED = "received"
EVENT_STATUS_IGNORED = "ignored"
EVENT_STATUS_ENQUEUED = "enqueued"
EVENT_STATUS_PROCESSED = "processed"
EVENT_STATUS_FAILED = "failed"

_ALLOWED_CURRENT_STATUSES_BY_TARGET_STATUS = {
    EVENT_STATUS_RECEIVED: {EVENT_STATUS_RECEIVED, EVENT_STATUS_FAILED},
    EVENT_STATUS_IGNORED: {
        EVENT_STATUS_IGNORED,
        EVENT_STATUS_RECEIVED,
        EVENT_STATUS_FAILED,
    },
    EVENT_STATUS_ENQUEUED: {EVENT_STATUS_ENQUEUED, EVENT_STATUS_RECEIVED},
    EVENT_STATUS_PROCESSED: {
        EVENT_STATUS_PROCESSED,
        EVENT_STATUS_RECEIVED,
        EVENT_STATUS_ENQUEUED,
    },
    EVENT_STATUS_FAILED: {
        EVENT_STATUS_FAILED,
        EVENT_STATUS_RECEIVED,
        EVENT_STATUS_ENQUEUED,
    },
}


def ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
                event_id TEXT PRIMARY KEY,
                merchant_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_created_at TEXT,
                data_type TEXT,
                data_id TEXT,
                order_id TEXT,
                order_state TEXT,
                location_id TEXT,
                version INTEGER,
                status TEXT NOT NULL,
                received_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def get_webhook_event(event_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT
                event_id,
                merchant_id,
                event_type,
                event_created_at,
                data_type,
                data_id,
                order_id,
                order_state,
                location_id,
                version,
                status,
                received_at,
                updated_at
            FROM webhook_events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "event_id": row[0],
        "merchant_id": row[1],
        "event_type": row[2],
        "event_created_at": row[3],
        "data_type": row[4],
        "data_id": row[5],
        "order_id": row[6],
        "order_state": row[7],
        "location_id": row[8],
        "version": row[9],
        "status": row[10],
        "received_at": row[11],
        "updated_at": row[12],
    }


def has_webhook_event(event_id):
    return get_webhook_event(event_id) is not None


def upsert_webhook_event(
    *,
    event_id,
    merchant_id,
    event_type,
    event_created_at=None,
    data_type=None,
    data_id=None,
    order_id=None,
    order_state=None,
    location_id=None,
    version=None,
    status=EVENT_STATUS_RECEIVED,
):
    ensure_db()
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO webhook_events (
                event_id,
                merchant_id,
                event_type,
                event_created_at,
                data_type,
                data_id,
                order_id,
                order_state,
                location_id,
                version,
                status,
                received_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                merchant_id = excluded.merchant_id,
                event_type = excluded.event_type,
                event_created_at = excluded.event_created_at,
                data_type = excluded.data_type,
                data_id = excluded.data_id,
                order_id = excluded.order_id,
                order_state = excluded.order_state,
                location_id = excluded.location_id,
                version = excluded.version,
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                event_id,
                merchant_id,
                event_type,
                event_created_at,
                data_type,
                data_id,
                order_id,
                order_state,
                location_id,
                version,
                status,
                now,
                now,
            ),
        )


def create_webhook_event(
    *,
    event_id,
    merchant_id,
    event_type,
    event_created_at=None,
    data_type=None,
    data_id=None,
    order_id=None,
    order_state=None,
    location_id=None,
    version=None,
    status=EVENT_STATUS_RECEIVED,
):
    ensure_db()
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            """
            INSERT INTO webhook_events (
                event_id,
                merchant_id,
                event_type,
                event_created_at,
                data_type,
                data_id,
                order_id,
                order_state,
                location_id,
                version,
                status,
                received_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO NOTHING
            """,
            (
                event_id,
                merchant_id,
                event_type,
                event_created_at,
                data_type,
                data_id,
                order_id,
                order_state,
                location_id,
                version,
                status,
                now,
                now,
            ),
        )

    return cursor.rowcount == 1


def set_webhook_event_status(event_id, status):
    ensure_db()
    allowed_current_statuses = _ALLOWED_CURRENT_STATUSES_BY_TARGET_STATUS.get(status)
    if not allowed_current_statuses:
        raise ValueError(f"Unsupported webhook event status transition target: {status}")

    placeholders = ", ".join("?" for _ in allowed_current_statuses)
    params = (
        status,
        datetime.now(UTC).isoformat(),
        event_id,
        *sorted(allowed_current_statuses),
    )
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            f"""
            UPDATE webhook_events
            SET status = ?, updated_at = ?
            WHERE event_id = ? AND status IN ({placeholders})
            """,
            params,
        )

    return cursor.rowcount == 1


def list_webhook_events(status=None):
    ensure_db()
    query = (
        "SELECT event_id, merchant_id, event_type, event_created_at, data_type, "
        "data_id, order_id, order_state, location_id, version, status, received_at, updated_at "
        "FROM webhook_events"
    )
    params = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY received_at DESC"

    with sqlite3.connect(DB_FILE) as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        {
            "event_id": row[0],
            "merchant_id": row[1],
            "event_type": row[2],
            "event_created_at": row[3],
            "data_type": row[4],
            "data_id": row[5],
            "order_id": row[6],
            "order_state": row[7],
            "location_id": row[8],
            "version": row[9],
            "status": row[10],
            "received_at": row[11],
            "updated_at": row[12],
        }
        for row in rows
    ]
