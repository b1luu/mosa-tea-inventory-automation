import unittest
from json import JSONDecodeError
from unittest.mock import patch

from app.sqs_worker import process_one_sqs_message


REAL_SUCCESS_JOB = {
    "event_id": "7636f400-d68c-3c80-8f5b-77b8427cab0d",
    "merchant_id": "ML9M9XX0HM717",
    "event_type": "order.updated",
    "order_id": "2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY",
}

REAL_SECOND_JOB = {
    "event_id": "5cda58c1-dc39-39b4-bdc9-2e3c644ffeaf",
    "merchant_id": "ML9M9XX0HM717",
    "event_type": "order.updated",
    "order_id": "KTnlBdi4M0PvK6jDTQK4gUTBP3PZY",
}


class SqsWorkerTests(unittest.TestCase):
    def test_process_one_sqs_message_returns_when_queue_is_empty(self):
        with patch("app.sqs_worker.receive_webhook_jobs", return_value=[]):
            result = process_one_sqs_message()

        self.assertEqual(result, {"message": "No webhook jobs available."})

    def test_process_one_sqs_message_processes_and_deletes_message(self):
        message = {
            "MessageId": "msg-1",
            "ReceiptHandle": "receipt-1",
            "Body": (
                '{"event_id": "7636f400-d68c-3c80-8f5b-77b8427cab0d", '
                '"merchant_id": "ML9M9XX0HM717", '
                '"event_type": "order.updated", '
                '"order_id": "2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"}'
            ),
        }

        with patch("app.sqs_worker.receive_webhook_jobs", return_value=[message]):
            with patch(
                "app.sqs_worker.process_webhook_job", return_value="applied"
            ) as mock_worker:
                with patch("app.sqs_worker.delete_webhook_job") as mock_delete:
                    result = process_one_sqs_message()

        mock_worker.assert_called_once_with(REAL_SUCCESS_JOB)
        mock_delete.assert_called_once_with("receipt-1")
        self.assertEqual(result["message_id"], "msg-1")
        self.assertEqual(result["processing_state"], "applied")
        self.assertTrue(result["deleted"])

    def test_process_one_sqs_message_does_not_delete_failed_processing(self):
        message = {
            "MessageId": "msg-2",
            "ReceiptHandle": "receipt-2",
            "Body": (
                '{"event_id": "5cda58c1-dc39-39b4-bdc9-2e3c644ffeaf", '
                '"merchant_id": "ML9M9XX0HM717", '
                '"event_type": "order.updated", '
                '"order_id": "KTnlBdi4M0PvK6jDTQK4gUTBP3PZY"}'
            ),
        }

        with patch("app.sqs_worker.receive_webhook_jobs", return_value=[message]):
            with patch(
                "app.sqs_worker.process_webhook_job",
                side_effect=RuntimeError("state not terminal"),
            ) as mock_worker:
                with patch("app.sqs_worker.delete_webhook_job") as mock_delete:
                    with self.assertRaises(RuntimeError):
                        process_one_sqs_message()

        mock_worker.assert_called_once_with(REAL_SECOND_JOB)
        mock_delete.assert_not_called()

    def test_process_one_sqs_message_does_not_delete_malformed_json(self):
        message = {
            "MessageId": "msg-3",
            "ReceiptHandle": "receipt-3",
            "Body": "{not-json",
        }

        with patch("app.sqs_worker.receive_webhook_jobs", return_value=[message]):
            with patch("app.sqs_worker.process_webhook_job") as mock_worker:
                with patch("app.sqs_worker.delete_webhook_job") as mock_delete:
                    with self.assertRaises(JSONDecodeError):
                        process_one_sqs_message()

        mock_worker.assert_not_called()
        mock_delete.assert_not_called()
