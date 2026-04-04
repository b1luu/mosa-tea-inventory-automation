import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path


DB_FILE = Path("data/oauth_state.db")


def _utcnow():
    return datetime.now(UTC)


def ensure_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_state (
                state TEXT PRIMARY KEY,
                environment TEXT NOT NULL,
                created_at TEXT NOT NULL,
                consumed_at TEXT
            )
            """
        )


def create_oauth_state(environment):
    ensure_db()
    state = str(uuid.uuid4())
    with sqlite3.connect(DB_FILE) as connection:
        connection.execute(
            """
            INSERT INTO oauth_state (state, environment, created_at, consumed_at)
            VALUES (?, ?, ?, NULL)
            """,
            (state, environment, _utcnow().isoformat()),
        )
    return state


def consume_oauth_state(state, *, max_age_seconds=600):
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        row = connection.execute(
            """
            SELECT state, environment, created_at, consumed_at
            FROM oauth_state
            WHERE state = ?
            """,
            (state,),
        ).fetchone()

        if not row:
            return None

        created_at = datetime.fromisoformat(row[2])
        consumed_at = row[3]
        if consumed_at is not None:
            return None

        if _utcnow() - created_at > timedelta(seconds=max_age_seconds):
            return None

        now = _utcnow().isoformat()
        cursor = connection.execute(
            """
            UPDATE oauth_state
            SET consumed_at = ?
            WHERE state = ? AND consumed_at IS NULL
            """,
            (now, state),
        )

    if cursor.rowcount != 1:
        return None

    return {
        "state": row[0],
        "environment": row[1],
        "created_at": row[2],
        "consumed_at": now,
    }
