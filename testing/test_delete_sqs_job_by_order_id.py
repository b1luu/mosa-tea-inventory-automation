import unittest
from unittest.mock import patch

from scripts.delete_sqs_job_by_order_id import main


class DeleteSqsJobByOrderIdTests(unittest.TestCase):
    def test_deletes_matching_message(self):
        messages = [
            {
                "MessageId": "msg-1",
                "ReceiptHandle": "receipt-1",
                "Body": '{"order_id": "order-1"}',
            },
            {
                "MessageId": "msg-2",
                "ReceiptHandle": "receipt-2",
                "Body": '{"order_id": "order-2"}',
            },
        ]

        with patch("sys.argv", ["delete_sqs_job_by_order_id", "order-2"]):
            with patch(
                "scripts.delete_sqs_job_by_order_id.receive_webhook_jobs",
                return_value=messages,
            ):
                with patch("scripts.delete_sqs_job_by_order_id.delete_webhook_job") as mock_delete:
                    with patch(
                        "scripts.delete_sqs_job_by_order_id.change_webhook_job_visibility"
                    ) as mock_visibility:
                        exit_code = main()

        self.assertEqual(exit_code, 0)
        mock_delete.assert_called_once_with("receipt-2")
        mock_visibility.assert_called_once_with("receipt-1", 0)

    def test_returns_nonzero_when_no_matching_message_found(self):
        messages = [
            {
                "MessageId": "msg-1",
                "ReceiptHandle": "receipt-1",
                "Body": '{"order_id": "other-order"}',
            }
        ]

        with patch("sys.argv", ["delete_sqs_job_by_order_id", "order-9", "1"]):
            with patch(
                "scripts.delete_sqs_job_by_order_id.receive_webhook_jobs",
                return_value=messages,
            ):
                with patch("scripts.delete_sqs_job_by_order_id.delete_webhook_job") as mock_delete:
                    with patch(
                        "scripts.delete_sqs_job_by_order_id.change_webhook_job_visibility"
                    ) as mock_visibility:
                        exit_code = main()

        self.assertEqual(exit_code, 1)
        mock_delete.assert_not_called()
        mock_visibility.assert_called_once_with("receipt-1", 0)
