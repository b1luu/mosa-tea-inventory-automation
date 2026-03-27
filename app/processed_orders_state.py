import sqlite3

from app.order_processing_db import DB_FILE, ensure_db, mark_order_applied


def load_processed_order_ids():
    ensure_db()
    with sqlite3.connect(DB_FILE) as connection:
        rows = connection.execute(
            "SELECT square_order_id FROM order_processing WHERE processing_state = 'applied'"
        ).fetchall()
    return {row[0] for row in rows}


def mark_orders_processed(order_ids):
    ensure_db()
    for order_id in order_ids:
        mark_order_applied(order_id)
