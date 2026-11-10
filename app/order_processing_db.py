import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, UTC
from pathlib import Path


DB_FILE = Path("data/order_processing.db")
PROCESSING_STATE_PENDING = "pending"
PROCESSING_STATE_PROCESSING = "processing"
PROCESSING_STATE_BLOCKED = "blocked"
PROCESSING_STATE_FAILED = "failed"
PROCESSING_STATE_APPLIED = "applied"
# Paid, then cancelled during the hold before apply: terminal, nothing deducted.
PROCESSING_STATE_CANCELLED_BEFORE_APPLY = "cancelled_before_apply"

# A `processing` claim untouched for this long belongs to a run that is dead: the
# worker Lambda is killed at its timeout (30 s), and a killed run never reaches the
# `except` that releases its claim. The next retry or replay may take it over.
# Two bounds, both enforced by testing/test_claim_lease.py:
# - longer than the worker Lambda timeout, or a live run could be taken over
#   (the worker's startup check enforces this one at runtime too);
# - shorter than the last SQS retry ((maxReceiveCount - 1) x visibility timeout,
#   240 s by default), or every retry finds the claim still fresh and the message
#   reaches the DLQ before any takeover. At 90 s, the retry at ~120 s takes over.
CLAIM_LEASE_SECONDS = 90


def stale_claim_cutoff(now):
    """Claims last touched before this ISO timestamp are past their lease."""
    return (now - timedelta(seconds=CLAIM_LEASE_SECONDS)).isoformat()


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


_CONTEXT_COLUMNS = ("merchant_id", "environment", "location_id")
_BACKFILLED_COLUMNS = (*_CONTEXT_COLUMNS, "updated_at")


def ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS order_processing (
                square_order_id TEXT PRIMARY KEY,
                processing_state TEXT NOT NULL,
                applied_at TEXT,
                merchant_id TEXT,
                environment TEXT,
                location_id TEXT,
                updated_at TEXT
            )
            """
        )
        # Backfill columns on dev databases created before they existed. Rows
        # reserved before this migration carry NULL context and are intentionally
        # not safe to replay (see replay_order_job); a NULL updated_at is never
        # treated as a stale claim.
        existing = {
            row[1]
            for row in connection.execute("PRAGMA table_info(order_processing)")
        }
        for column in _BACKFILLED_COLUMNS:
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE order_processing ADD COLUMN {column} TEXT"
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


def get_order_processing_record(order_id):
    ensure_db()
    with _db_connection() as connection:
        row = connection.execute(
            "SELECT square_order_id, processing_state, applied_at, "
            "merchant_id, environment, location_id "
            "FROM order_processing WHERE square_order_id = ?",
            (order_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "square_order_id": row[0],
        "processing_state": row[1],
        "applied_at": row[2],
        "merchant_id": row[3],
        "environment": row[4],
        "location_id": row[5],
    }


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
    # NOTE: this upsert only sets processing_state/applied_at. On an existing
    # row it PRESERVES the merchant context columns (merchant_id/environment/
    # location_id); on a brand-new row those columns are NULL. The DynamoDB
    # backend's set_order_processing_state does a full put and would instead
    # DROP that context — prefer transition_order_processing_state (a partial
    # update) for state changes that must retain merchant context.
    ensure_db()
    now = datetime.now(UTC).isoformat()
    applied_at = now if processing_state == PROCESSING_STATE_APPLIED else None
    with _db_connection() as connection:
        connection.execute(
            """
            INSERT INTO order_processing (
                square_order_id, processing_state, applied_at, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(square_order_id) DO UPDATE SET
                processing_state = excluded.processing_state,
                applied_at = excluded.applied_at,
                updated_at = excluded.updated_at
            """,
            (order_id, processing_state, applied_at, now),
        )


def transition_order_processing_state(order_id, from_state, to_state):
    ensure_db()
    now = datetime.now(UTC).isoformat()
    applied_at = now if to_state == PROCESSING_STATE_APPLIED else None
    with _db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE order_processing
            SET processing_state = ?, applied_at = ?, updated_at = ?
            WHERE square_order_id = ? AND processing_state = ?
            """,
            (to_state, applied_at, now, order_id, from_state),
        )

    return cursor.rowcount == 1


def reserve_order_processing(
    order_id,
    *,
    merchant_id=None,
    environment=None,
    location_id=None,
):
    ensure_db()
    with _db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO order_processing (
                square_order_id, processing_state, applied_at,
                merchant_id, environment, location_id, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(square_order_id) DO NOTHING
            """,
            (
                order_id,
                PROCESSING_STATE_PENDING,
                None,
                merchant_id,
                environment,
                location_id,
                datetime.now(UTC).isoformat(),
            ),
        )
        reserved = cursor.rowcount == 1

    return reserved


def claim_order_processing(order_id):
    """Claim a pending order, or take over a claim older than the lease.

    One conditional UPDATE, so of two runs racing for the same order only one
    wins. A fresh `processing` claim (a live run) is never taken over.
    """
    ensure_db()
    now = datetime.now(UTC)
    with _db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE order_processing
            SET processing_state = ?, updated_at = ?
            WHERE square_order_id = ?
              AND (
                processing_state = ?
                OR (processing_state = ? AND updated_at < ?)
              )
            """,
            (
                PROCESSING_STATE_PROCESSING,
                now.isoformat(),
                order_id,
                PROCESSING_STATE_PENDING,
                PROCESSING_STATE_PROCESSING,
                stale_claim_cutoff(now),
            ),
        )

    return cursor.rowcount == 1


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


def mark_order_cancelled_before_apply(order_id):
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PROCESSING,
        PROCESSING_STATE_CANCELLED_BEFORE_APPLY,
    )
