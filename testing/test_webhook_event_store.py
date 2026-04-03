import unittest
from unittest.mock import patch

from app import webhook_event_store


class WebhookEventStoreTests(unittest.TestCase):
    def test_uses_sqlite_backend_by_default(self):
        with patch(
            "app.webhook_event_store.get_webhook_event_store_mode",
            return_value="sqlite",
        ):
            with patch(
                "app.webhook_event_store.webhook_event_db.get_webhook_event",
                return_value={"event_id": "evt-1"},
            ) as mock_sqlite:
                event = webhook_event_store.get_webhook_event("evt-1")

        self.assertEqual(event, {"event_id": "evt-1"})
        mock_sqlite.assert_called_once_with("evt-1")

    def test_uses_dynamodb_backend_when_configured(self):
        with patch(
            "app.webhook_event_store.get_webhook_event_store_mode",
            return_value="dynamodb",
        ):
            with patch(
                "app.webhook_event_store.webhook_event_dynamodb.set_webhook_event_status",
                return_value=True,
            ) as mock_dynamodb:
                transitioned = webhook_event_store.set_webhook_event_status(
                    "evt-1", "processed"
                )

        self.assertTrue(transitioned)
        mock_dynamodb.assert_called_once_with("evt-1", "processed")

    def test_create_webhook_event_uses_backend_create_when_available(self):
        with patch(
            "app.webhook_event_store.get_webhook_event_store_mode",
            return_value="dynamodb",
        ):
            with patch(
                "app.webhook_event_store.webhook_event_dynamodb.create_webhook_event",
                return_value=True,
            ) as mock_dynamodb:
                created = webhook_event_store.create_webhook_event(
                    event_id="evt-1",
                    merchant_id="merchant-1",
                    event_type="order.updated",
                )

        self.assertTrue(created)
        mock_dynamodb.assert_called_once_with(
            event_id="evt-1",
            merchant_id="merchant-1",
            event_type="order.updated",
        )
