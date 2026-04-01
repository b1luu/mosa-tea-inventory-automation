import sqlite3
from datetime import datetime, UTC
from pathlib import Path


DB_FILE = Path("data/order_processing.db")
PROCESSING_STATE_PENDING = "pending"
PROCESSING_STATE_BLOCKED = "blocked"
PROCESSING_STATE_FAILED = "failed"
PROCESSING_STATE_APPLIED = "applied"


def ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS order_processing (
                square_order_id TEXT PRIMARY KEY,
                processing_state TEXT NOT NULL,
                applied_at TEXT
            )
            """
        )


def is_order_applied(order_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            "SELECT processing_state FROM order_processing WHERE square_order_id = ?",
            (order_id,),
        ).fetchone()
    return bool(row and row[0] == PROCESSING_STATE_APPLIED)


def get_order_processing_state(order_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            "SELECT processing_state FROM order_processing WHERE square_order_id = ?",
            (order_id,),
        ).fetchone()
    return row[0] if row else None


def list_order_processing_rows(processing_state=None):
    ensure_db()
    query = (
        "SELECT square_order_id, processing_state, applied_at "
        "FROM order_processing"
    )
    params = ()
    if processing_state:
        query += " WHERE processing_state = ?"
        params = (processing_state,)
    query += " ORDER BY rowid DESC"

    with sqlite3.connect(DB_FILE) as connection:
        rows = connection.execute(query, params).fetchall()

    return [
        {
            "square_order_id": row[0],
            "processing_state": row[1],
            "applied_at": row[2],
        }
        for row in rows
    ]


def set_order_processing_state(order_id, processing_state):
    ensure_db()
    applied_at = (
        datetime.now(UTC).isoformat()
        if processing_state == PROCESSING_STATE_APPLIED
        else None
    )
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO order_processing (square_order_id, processing_state, applied_at)
            VALUES (?, ?, ?)
            ON CONFLICT(square_order_id) DO UPDATE SET
                processing_state = excluded.processing_state,
                applied_at = excluded.applied_at
            """,
            (order_id, processing_state, applied_at),
        )


def reserve_order_processing(order_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            """
            INSERT INTO order_processing (square_order_id, processing_state, applied_at)
            VALUES (?, ?, ?)
            ON CONFLICT(square_order_id) DO NOTHING
            """,
            (order_id, PROCESSING_STATE_PENDING, None),
        )
        reserved = cursor.rowcount == 1

    return reserved


def clear_order_processing_reservation(order_id):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        cursor = connection.execute(
            """
            DELETE FROM order_processing
            WHERE square_order_id = ? AND processing_state = ?
            """,
            (order_id, PROCESSING_STATE_PENDING),
        )

    return cursor.rowcount == 1


def mark_order_applied(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_APPLIED)


def mark_order_pending(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_PENDING)


def mark_order_failed(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_FAILED)
