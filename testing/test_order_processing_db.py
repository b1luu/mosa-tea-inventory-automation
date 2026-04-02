import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import order_processing_db


class OrderProcessingDbTests(unittest.TestCase):
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

                order_processing_db.mark_order_pending("order-2")
                self.assertTrue(order_processing_db.mark_order_applied("order-2"))
                self.assertFalse(
                    order_processing_db.clear_order_processing_reservation("order-2")
                )
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-2"),
                    order_processing_db.PROCESSING_STATE_APPLIED,
                )

    def test_terminal_transitions_only_succeed_from_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "order_processing.db"
            with patch.object(order_processing_db, "DB_FILE", db_path):
                order_processing_db.mark_order_pending("order-1")
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
                order_processing_db.mark_order_pending("order-2")
                self.assertTrue(order_processing_db.mark_order_blocked("order-2"))
                self.assertEqual(
                    order_processing_db.get_order_processing_state("order-2"),
                    order_processing_db.PROCESSING_STATE_BLOCKED,
                )

                self.assertFalse(order_processing_db.mark_order_blocked("order-2"))
