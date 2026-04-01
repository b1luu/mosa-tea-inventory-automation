import unittest
from unittest.mock import patch

from app.webhook_worker import process_webhook_job


REAL_SUCCESS_JOB = {
    "event_id": "7636f400-d68c-3c80-8f5b-77b8427cab0d",
    "merchant_id": "ML9M9XX0HM717",
    "event_type": "order.updated",
    "order_id": "2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY",
}


class WebhookWorkerTests(unittest.TestCase):
    def test_process_webhook_job_marks_processed_for_applied_orders(self):
        with patch("app.webhook_worker.process_orders") as mock_process:
            with patch(
                "app.webhook_worker.get_order_processing_state", return_value="applied"
            ):
                with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
                    result = process_webhook_job(REAL_SUCCESS_JOB)

        mock_process.assert_called_once_with(
            ["2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"], apply_changes=True
        )
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "processed"
        )
        self.assertEqual(result, "applied")

    def test_process_webhook_job_marks_processed_for_blocked_orders(self):
        with patch("app.webhook_worker.process_orders") as mock_process:
            with patch(
                "app.webhook_worker.get_order_processing_state", return_value="blocked"
            ):
                with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
                    result = process_webhook_job(REAL_SUCCESS_JOB)

        mock_process.assert_called_once_with(
            ["2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"], apply_changes=True
        )
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "processed"
        )
        self.assertEqual(result, "blocked")

    def test_process_webhook_job_marks_failed_when_state_is_not_terminal(self):
        with patch("app.webhook_worker.process_orders") as mock_process:
            with patch(
                "app.webhook_worker.get_order_processing_state", return_value="failed"
            ):
                with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
                    with self.assertRaises(RuntimeError):
                        process_webhook_job(REAL_SUCCESS_JOB)

        mock_process.assert_called_once_with(
            ["2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"], apply_changes=True
        )
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "failed"
        )

    def test_process_webhook_job_marks_failed_when_order_id_is_missing(self):
        with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
            with self.assertRaises(KeyError):
                process_webhook_job(
                    {
                        "event_id": "7636f400-d68c-3c80-8f5b-77b8427cab0d",
                        "merchant_id": "ML9M9XX0HM717",
                        "event_type": "order.updated",
                    }
                )

        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "failed"
        )
