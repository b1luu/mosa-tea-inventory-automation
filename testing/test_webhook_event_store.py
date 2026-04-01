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
                "app.webhook_event_store.webhook_event_dynamodb.set_webhook_event_status"
            ) as mock_dynamodb:
                webhook_event_store.set_webhook_event_status("evt-1", "processed")

        mock_dynamodb.assert_called_once_with("evt-1", "processed")
