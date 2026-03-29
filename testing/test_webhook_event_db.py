import tempfile
import unittest
from pathlib import Path

from app import webhook_event_db


class WebhookEventDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = webhook_event_db.DB_FILE
        webhook_event_db.DB_FILE = Path(self.temp_dir.name) / "webhook_events.db"

    def tearDown(self):
        webhook_event_db.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_upsert_and_fetch_square_shaped_event_record(self):
        webhook_event_db.upsert_webhook_event(
            event_id="evt-1",
            merchant_id="merchant-1",
            event_type="order.updated",
            event_created_at="2026-03-29T00:00:00Z",
            data_type="order_updated",
            data_id="order-1",
            order_id="order-1",
            order_state="COMPLETED",
            location_id="loc-1",
            version=4,
        )

        event = webhook_event_db.get_webhook_event("evt-1")

        self.assertIsNotNone(event)
        self.assertEqual(event["event_id"], "evt-1")
        self.assertEqual(event["merchant_id"], "merchant-1")
        self.assertEqual(event["event_type"], "order.updated")
        self.assertEqual(event["event_created_at"], "2026-03-29T00:00:00Z")
        self.assertEqual(event["data_type"], "order_updated")
        self.assertEqual(event["data_id"], "order-1")
        self.assertEqual(event["order_id"], "order-1")
        self.assertEqual(event["order_state"], "COMPLETED")
        self.assertEqual(event["location_id"], "loc-1")
        self.assertEqual(event["version"], 4)
        self.assertEqual(event["status"], webhook_event_db.EVENT_STATUS_RECEIVED)

    def test_set_webhook_event_status(self):
        webhook_event_db.upsert_webhook_event(
            event_id="evt-2",
            merchant_id="merchant-2",
            event_type="order.created",
        )

        webhook_event_db.set_webhook_event_status(
            "evt-2",
            webhook_event_db.EVENT_STATUS_PROCESSED,
        )

        event = webhook_event_db.get_webhook_event("evt-2")
        self.assertEqual(event["status"], webhook_event_db.EVENT_STATUS_PROCESSED)


if __name__ == "__main__":
    unittest.main()
