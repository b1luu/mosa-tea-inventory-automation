import unittest
from unittest.mock import patch

from app import order_processing_store


class OrderProcessingStoreTests(unittest.TestCase):
    def test_uses_sqlite_backend_by_default(self):
        with patch(
            "app.order_processing_store.get_order_processing_store_mode",
            return_value="sqlite",
        ):
            with patch(
                "app.order_processing_store.order_processing_db.get_order_processing_state",
                return_value="pending",
            ) as mock_sqlite:
                state = order_processing_store.get_order_processing_state("order-1")

        self.assertEqual(state, "pending")
        mock_sqlite.assert_called_once_with("order-1")

    def test_uses_dynamodb_backend_when_configured(self):
        with patch(
            "app.order_processing_store.get_order_processing_store_mode",
            return_value="dynamodb",
        ):
            with patch(
                "app.order_processing_store.order_processing_dynamodb.reserve_order_processing",
                return_value=True,
            ) as mock_dynamodb:
                reserved = order_processing_store.reserve_order_processing("order-1")

        self.assertTrue(reserved)
        mock_dynamodb.assert_called_once_with("order-1")

    def test_claim_order_processing_uses_configured_backend(self):
        with patch(
            "app.order_processing_store.get_order_processing_store_mode",
            return_value="dynamodb",
        ):
            with patch(
                "app.order_processing_store.order_processing_dynamodb.claim_order_processing",
                return_value=True,
            ) as mock_dynamodb:
                claimed = order_processing_store.claim_order_processing("order-1")

        self.assertTrue(claimed)
        mock_dynamodb.assert_called_once_with("order-1")

    def test_requeue_order_processing_uses_configured_backend(self):
        with patch(
            "app.order_processing_store.get_order_processing_store_mode",
            return_value="dynamodb",
        ):
            with patch(
                "app.order_processing_store.order_processing_dynamodb.requeue_order_processing",
                return_value=True,
            ) as mock_dynamodb:
                requeued = order_processing_store.requeue_order_processing("order-1")

        self.assertTrue(requeued)
        mock_dynamodb.assert_called_once_with("order-1")
