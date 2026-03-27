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
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            "SELECT processing_state FROM order_processing WHERE square_order_id = ?",
            (order_id,),
        ).fetchone()
    return bool(row and row[0] == PROCESSING_STATE_APPLIED)


def get_order_processing_state(order_id):
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            "SELECT processing_state FROM order_processing WHERE square_order_id = ?",
            (order_id,),
        ).fetchone()
    return row[0] if row else None


def set_order_processing_state(order_id, processing_state):
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


def mark_order_applied(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_APPLIED)
