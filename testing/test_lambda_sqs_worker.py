import unittest
from unittest.mock import patch

from app.lambda_sqs_worker import lambda_handler


class LambdaSqsWorkerTests(unittest.TestCase):
    def test_lambda_handler_processes_successful_records(self):
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": '{"event_id": "evt-1", "order_id": "order-1"}',
                }
            ]
        }

        with patch("app.lambda_sqs_worker.process_webhook_job") as mock_worker:
            result = lambda_handler(event, context=None)

        mock_worker.assert_called_once_with({"event_id": "evt-1", "order_id": "order-1"})
        self.assertEqual(result, {"batchItemFailures": []})

    def test_lambda_handler_returns_partial_batch_failures(self):
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": '{"event_id": "evt-1", "order_id": "order-1"}',
                },
                {
                    "messageId": "msg-2",
                    "body": '{"event_id": "evt-2", "order_id": "order-2"}',
                },
            ]
        }

        def side_effect(job):
            if job["order_id"] == "order-2":
                raise RuntimeError("boom")

        with patch("app.lambda_sqs_worker.process_webhook_job", side_effect=side_effect):
            result = lambda_handler(event, context=None)

        self.assertEqual(
            result,
            {"batchItemFailures": [{"itemIdentifier": "msg-2"}]},
        )

    def test_lambda_handler_treats_non_terminal_worker_state_as_failure(self):
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": '{"event_id": "evt-1", "order_id": "order-1"}',
                }
            ]
        }

        with patch(
            "app.lambda_sqs_worker.process_webhook_job",
            side_effect=RuntimeError("state not terminal"),
        ):
            result = lambda_handler(event, context=None)

        self.assertEqual(
            result,
            {"batchItemFailures": [{"itemIdentifier": "msg-1"}]},
        )
