import sqlite3
from pathlib import Path


DB_FILE = Path("data/order_processing.sqlite3")


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
