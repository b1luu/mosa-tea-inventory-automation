import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_FILE = Path("data/usage_log.db")


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
            CREATE TABLE IF NOT EXISTS usage_log (
                usage_key TEXT NOT NULL,
                sold_at_order_id TEXT NOT NULL,
                environment TEXT NOT NULL,
                merchant_id TEXT NOT NULL,
                location_id TEXT NOT NULL,
                inventory_key TEXT NOT NULL,
                order_id TEXT NOT NULL,
                sold_at TEXT NOT NULL,
                amount TEXT NOT NULL,
                unit TEXT NOT NULL,
                PRIMARY KEY (usage_key, sold_at_order_id)
            )
            """
        )


def put_usage_rows(rows):
    ensure_db()
    with _db_connection() as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO usage_log (
                usage_key, sold_at_order_id, environment, merchant_id, location_id,
                inventory_key, order_id, sold_at, amount, unit
            ) VALUES (
                :usage_key, :sold_at_order_id, :environment, :merchant_id, :location_id,
                :inventory_key, :order_id, :sold_at, :amount, :unit
            )
            """,
            rows,
        )


def query_usage_rows(usage_key, start_sold_at, end_sold_at):
    ensure_db()
    with _db_connection() as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.execute(
            """
            SELECT * FROM usage_log
            WHERE usage_key = ? AND sold_at_order_id >= ? AND sold_at_order_id < ?
            ORDER BY sold_at_order_id
            """,
            (usage_key, start_sold_at, end_sold_at),
        )
        return [dict(row) for row in cursor.fetchall()]
