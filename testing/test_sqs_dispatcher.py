import json
import unittest
from unittest.mock import Mock, patch

from app.sqs_dispatcher import dispatch_webhook_job_to_sqs


class SqsDispatcherTests(unittest.TestCase):
    def test_dispatch_webhook_job_to_sqs_sends_serialized_job(self):
        job = {
            "event_id": "evt-1",
            "merchant_id": "merchant-1",
            "event_type": "order.updated",
            "order_id": "order-1",
        }
        mock_client = Mock()

        with patch("app.sqs_dispatcher._create_sqs_client", return_value=mock_client):
            with patch(
                "app.sqs_dispatcher.get_webhook_job_queue_url",
                return_value="https://sqs.us-west-2.amazonaws.com/123/jobs",
            ):
                dispatch_webhook_job_to_sqs(job)

        mock_client.send_message.assert_called_once_with(
            QueueUrl="https://sqs.us-west-2.amazonaws.com/123/jobs",
            MessageBody=json.dumps(job),
        )


    def _send(self, job):
        mock_client = Mock()
        with patch("app.sqs_dispatcher._create_sqs_client", return_value=mock_client):
            with patch(
                "app.sqs_dispatcher.get_webhook_job_queue_url",
                return_value="https://sqs.us-west-2.amazonaws.com/123/jobs",
            ):
                dispatch_webhook_job_to_sqs(job)
        return mock_client.send_message.call_args.kwargs

    def test_held_job_is_sent_with_a_delay(self):
        sent = self._send({"order_id": "order-1", "hold_seconds": 900})

        self.assertEqual(sent["DelaySeconds"], 900)

    def test_hold_is_capped_at_the_sqs_maximum(self):
        sent = self._send({"order_id": "order-1", "hold_seconds": 3600})

        self.assertEqual(sent["DelaySeconds"], 900)

    def test_job_without_hold_has_no_delay(self):
        sent = self._send({"order_id": "order-1"})

        self.assertNotIn("DelaySeconds", sent)

if __name__ == "__main__":
    unittest.main()
