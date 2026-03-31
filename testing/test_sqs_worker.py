import unittest
from unittest.mock import patch

from app.sqs_worker import process_one_sqs_message


class SqsWorkerTests(unittest.TestCase):
    def test_process_one_sqs_message_returns_when_queue_is_empty(self):
        with patch("app.sqs_worker.receive_webhook_jobs", return_value=[]):
            result = process_one_sqs_message()

        self.assertEqual(result, {"message": "No webhook jobs available."})

    def test_process_one_sqs_message_processes_and_deletes_message(self):
        message = {
            "MessageId": "msg-1",
            "ReceiptHandle": "receipt-1",
            "Body": '{"event_id": "evt-1", "order_id": "order-1"}',
        }

        with patch("app.sqs_worker.receive_webhook_jobs", return_value=[message]):
            with patch("app.sqs_worker.process_webhook_job") as mock_worker:
                with patch(
                    "app.sqs_worker.get_order_processing_state", return_value="applied"
                ):
                    with patch("app.sqs_worker.delete_webhook_job") as mock_delete:
                        result = process_one_sqs_message()

        mock_worker.assert_called_once_with({"event_id": "evt-1", "order_id": "order-1"})
        mock_delete.assert_called_once_with("receipt-1")
        self.assertEqual(result["message_id"], "msg-1")
        self.assertEqual(result["processing_state"], "applied")
        self.assertTrue(result["deleted"])

    def test_process_one_sqs_message_does_not_delete_failed_processing(self):
        message = {
            "MessageId": "msg-2",
            "ReceiptHandle": "receipt-2",
            "Body": '{"event_id": "evt-2", "order_id": "order-2"}',
        }

        with patch("app.sqs_worker.receive_webhook_jobs", return_value=[message]):
            with patch("app.sqs_worker.process_webhook_job") as mock_worker:
                with patch("app.sqs_worker.get_order_processing_state", return_value="failed"):
                    with patch("app.sqs_worker.delete_webhook_job") as mock_delete:
                        with self.assertRaises(RuntimeError):
                            process_one_sqs_message()

        mock_worker.assert_called_once_with({"event_id": "evt-2", "order_id": "order-2"})
        mock_delete.assert_not_called()
