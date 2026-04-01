import unittest
from unittest.mock import patch

from app.webhook_worker import process_webhook_job


class WebhookWorkerTests(unittest.TestCase):
    def test_process_webhook_job_marks_processed_for_applied_orders(self):
        with patch("app.webhook_worker.process_orders") as mock_process:
            with patch(
                "app.webhook_worker.get_order_processing_state", return_value="applied"
            ):
                with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
                    result = process_webhook_job(
                        {"event_id": "evt-1", "order_id": "order-1"}
                    )

        mock_process.assert_called_once_with(["order-1"], apply_changes=True)
        mock_status.assert_called_once_with("evt-1", "processed")
        self.assertEqual(result, "applied")

    def test_process_webhook_job_marks_processed_for_blocked_orders(self):
        with patch("app.webhook_worker.process_orders") as mock_process:
            with patch(
                "app.webhook_worker.get_order_processing_state", return_value="blocked"
            ):
                with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
                    result = process_webhook_job(
                        {"event_id": "evt-1", "order_id": "order-1"}
                    )

        mock_process.assert_called_once_with(["order-1"], apply_changes=True)
        mock_status.assert_called_once_with("evt-1", "processed")
        self.assertEqual(result, "blocked")

    def test_process_webhook_job_marks_failed_when_state_is_not_terminal(self):
        with patch("app.webhook_worker.process_orders") as mock_process:
            with patch(
                "app.webhook_worker.get_order_processing_state", return_value="failed"
            ):
                with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
                    with self.assertRaises(RuntimeError):
                        process_webhook_job({"event_id": "evt-1", "order_id": "order-1"})

        mock_process.assert_called_once_with(["order-1"], apply_changes=True)
        mock_status.assert_called_once_with("evt-1", "failed")

    def test_process_webhook_job_marks_failed_when_order_id_is_missing(self):
        with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
            with self.assertRaises(KeyError):
                process_webhook_job({"event_id": "evt-1"})

        mock_status.assert_called_once_with("evt-1", "failed")
