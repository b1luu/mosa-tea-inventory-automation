import sqlite3
from contextlib import contextmanager
from datetime import datetime, UTC
from pathlib import Path


DB_FILE = Path("data/order_processing.db")
PROCESSING_STATE_PENDING = "pending"
PROCESSING_STATE_PROCESSING = "processing"
PROCESSING_STATE_BLOCKED = "blocked"
PROCESSING_STATE_FAILED = "failed"
PROCESSING_STATE_APPLIED = "applied"


@contextmanager
def _db_connection():
    connection = sqlite3.connect(DB_FILE)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _db_connection() as connection:
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
    with _db_connection() as connection:
        row = connection.execute(
            "SELECT processing_state FROM order_processing WHERE square_order_id = ?",
            (order_id,),
        ).fetchone()
    return bool(row and row[0] == PROCESSING_STATE_APPLIED)


def get_order_processing_state(order_id):
    ensure_db()
    with _db_connection() as connection:
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

    with _db_connection() as connection:
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
    with _db_connection() as connection:
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


def transition_order_processing_state(order_id, from_state, to_state):
    ensure_db()
    applied_at = datetime.now(UTC).isoformat() if to_state == PROCESSING_STATE_APPLIED else None
    with _db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE order_processing
            SET processing_state = ?, applied_at = ?
            WHERE square_order_id = ? AND processing_state = ?
            """,
            (to_state, applied_at, order_id, from_state),
        )

    return cursor.rowcount == 1


def reserve_order_processing(order_id):
    ensure_db()
    with _db_connection() as connection:
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


def claim_order_processing(order_id):
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PENDING,
        PROCESSING_STATE_PROCESSING,
    )


def release_order_processing_claim(order_id):
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PROCESSING,
        PROCESSING_STATE_PENDING,
    )


def requeue_order_processing(order_id):
    if transition_order_processing_state(
        order_id,
        PROCESSING_STATE_FAILED,
        PROCESSING_STATE_PENDING,
    ):
        return True

    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_BLOCKED,
        PROCESSING_STATE_PENDING,
    )


def clear_order_processing_reservation(order_id):
    ensure_db()
    with _db_connection() as connection:
        cursor = connection.execute(
            """
            DELETE FROM order_processing
            WHERE square_order_id = ? AND processing_state = ?
            """,
            (order_id, PROCESSING_STATE_PENDING),
        )

    return cursor.rowcount == 1


def mark_order_applied(order_id):
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PROCESSING,
        PROCESSING_STATE_APPLIED,
    )


def mark_order_pending(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_PENDING)


def mark_order_failed(order_id):
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PROCESSING,
        PROCESSING_STATE_FAILED,
    )


def mark_order_blocked(order_id):
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PROCESSING,
        PROCESSING_STATE_BLOCKED,
    )
