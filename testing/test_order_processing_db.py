import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import order_processing_db


def _read_context_row(db_path, order_id):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(
            "SELECT merchant_id, environment, location_id "
            "FROM order_processing WHERE square_order_id = ?",
            (order_id,),
        ).fetchone()
    finally:
        connection.close()


class OrderProcessingDbTests(unittest.TestCase):
    def test_reserve_persists_merchant_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing(
                    "order-1",
                    merchant_id="ML9M9XX0HM717",
                    environment="sandbox",
                    location_id="LB1MECVA7EZ8Z",
                )
            self.assertEqual(
                _read_context_row(db_path, "order-1"),
                ("ML9M9XX0HM717", "sandbox", "LB1MECVA7EZ8Z"),
            )

    def test_reserve_without_context_stores_nulls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing("order-1")
            self.assertEqual(_read_context_row(db_path, "order-1"), (None, None, None))

    def test_ensure_db_migrates_legacy_table_missing_context_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE order_processing ("
                "square_order_id TEXT PRIMARY KEY, "
                "processing_state TEXT NOT NULL, applied_at TEXT)"
            )
            connection.commit()
            connection.close()

            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.ensure_db()
                order_processing_db.reserve_order_processing(
                    "order-1",
                    merchant_id="ML9M9XX0HM717",
                    environment="sandbox",
                    location_id="LB1MECVA7EZ8Z",
                )

            self.assertEqual(
                _read_context_row(db_path, "order-1"),
                ("ML9M9XX0HM717", "sandbox", "LB1MECVA7EZ8Z"),
            )

    def test_get_order_processing_record_returns_full_row_with_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing(
                    "order-1",
                    merchant_id="ML9M9XX0HM717",
                    environment="sandbox",
                    location_id="LB1MECVA7EZ8Z",
                )
                record = order_processing_db.get_order_processing_record("order-1")

            self.assertEqual(record["square_order_id"], "order-1")
            self.assertEqual(record["processing_state"], "pending")
            self.assertEqual(record["merchant_id"], "ML9M9XX0HM717")
            self.assertEqual(record["environment"], "sandbox")
            self.assertEqual(record["location_id"], "LB1MECVA7EZ8Z")

    def test_get_order_processing_record_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                self.assertIsNone(
                    order_processing_db.get_order_processing_record("missing")
                )

    def test_reserve_order_processing_only_succeeds_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                self.assertTrue(order_processing_db.reserve_order_processing("order-1"))
                self.assertFalse(order_processing_db.reserve_order_processing("order-1"))
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-1"),
                    order_processing_db.PROCESSING_STATE_PENDING,
                )

    def test_clear_order_processing_reservation_only_clears_pending_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing("order-1")
                self.assertTrue(
                    order_processing_db.clear_order_processing_reservation("order-1")
                )
                self.assertIsNone(
                    order_processing_db.get_order_processing_state("order-1")
                )

                order_processing_db.reserve_order_processing("order-2")
                self.assertTrue(order_processing_db.claim_order_processing("order-2"))
                self.assertTrue(order_processing_db.mark_order_applied("order-2"))
                self.assertFalse(
                    order_processing_db.clear_order_processing_reservation("order-2")
                )
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-2"),
                    order_processing_db.PROCESSING_STATE_APPLIED,
                )

    def test_claim_and_release_order_processing_lease(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing("order-1")
                self.assertTrue(order_processing_db.claim_order_processing("order-1"))
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-1"),
                    order_processing_db.PROCESSING_STATE_PROCESSING,
                )
                self.assertTrue(
                    order_processing_db.release_order_processing_claim("order-1")
                )
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-1"),
                    order_processing_db.PROCESSING_STATE_PENDING,
                )

    def test_terminal_transitions_only_succeed_from_processing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing("order-1")
                self.assertFalse(order_processing_db.mark_order_applied("order-1"))
                self.assertTrue(order_processing_db.claim_order_processing("order-1"))
                self.assertTrue(order_processing_db.mark_order_applied("order-1"))
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-1"),
                    order_processing_db.PROCESSING_STATE_APPLIED,
                )

                self.assertFalse(order_processing_db.mark_order_failed("order-1"))
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-1"),
                    order_processing_db.PROCESSING_STATE_APPLIED,
                )

    def test_mark_order_blocked_requires_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing("order-2")
                self.assertFalse(order_processing_db.mark_order_blocked("order-2"))
                self.assertTrue(order_processing_db.claim_order_processing("order-2"))
                self.assertTrue(order_processing_db.mark_order_blocked("order-2"))
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-2"),
                    order_processing_db.PROCESSING_STATE_BLOCKED,
                )

                self.assertFalse(order_processing_db.mark_order_blocked("order-2"))

    def test_requeue_order_processing_only_succeeds_from_failed_or_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing("failed-order")
                order_processing_db.claim_order_processing("failed-order")
                order_processing_db.mark_order_failed("failed-order")
                self.assertTrue(
                    order_processing_db.requeue_order_processing("failed-order")
                )
                self.assertEqual(
                    order_processing_db.get_order_processing_state("failed-order"),
                    order_processing_db.PROCESSING_STATE_PENDING,
                )

                order_processing_db.reserve_order_processing("blocked-order")
                order_processing_db.claim_order_processing("blocked-order")
                order_processing_db.mark_order_blocked("blocked-order")
                self.assertTrue(
                    order_processing_db.requeue_order_processing("blocked-order")
                )
                self.assertEqual(
                    order_processing_db.get_order_processing_state("blocked-order"),
                    order_processing_db.PROCESSING_STATE_PENDING,
                )

                order_processing_db.reserve_order_processing("pending-order")
                self.assertFalse(
                    order_processing_db.requeue_order_processing("pending-order")
                )

    def test_cancelled_before_apply_is_a_terminal_transition_from_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.reserve_order_processing("order-1")
                self.assertFalse(order_processing_db.mark_order_cancelled_before_apply("order-1"))
                self.assertTrue(order_processing_db.claim_order_processing("order-1"))
                self.assertTrue(order_processing_db.mark_order_cancelled_before_apply("order-1"))
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-1"),
                    order_processing_db.PROCESSING_STATE_CANCELLED_BEFORE_APPLY,
                )
