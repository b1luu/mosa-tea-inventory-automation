import unittest
from unittest.mock import patch

from app.lambda_sqs_worker import lambda_handler


REAL_SUCCESS_JOB_BODY = (
    '{"event_id": "7636f400-d68c-3c80-8f5b-77b8427cab0d", '
    '"merchant_id": "ML9M9XX0HM717", '
    '"event_type": "order.updated", '
    '"order_id": "2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"}'
)

REAL_FAILURE_JOB_BODY = (
    '{"event_id": "5cda58c1-dc39-39b4-bdc9-2e3c644ffeaf", '
    '"merchant_id": "ML9M9XX0HM717", '
    '"event_type": "order.updated", '
    '"order_id": "KTnlBdi4M0PvK6jDTQK4gUTBP3PZY"}'
)


class LambdaSqsWorkerTests(unittest.TestCase):
    def test_lambda_handler_processes_successful_records(self):
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": REAL_SUCCESS_JOB_BODY,
                }
            ]
        }

        with patch("app.lambda_sqs_worker.process_webhook_job") as mock_worker:
            result = lambda_handler(event, context=None)

        mock_worker.assert_called_once_with(
            {
                "event_id": "7636f400-d68c-3c80-8f5b-77b8427cab0d",
                "merchant_id": "ML9M9XX0HM717",
                "event_type": "order.updated",
                "order_id": "2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY",
            }
        )
        self.assertEqual(result, {"batchItemFailures": []})

    def test_lambda_handler_returns_partial_batch_failures(self):
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": REAL_SUCCESS_JOB_BODY,
                },
                {
                    "messageId": "msg-2",
                    "body": REAL_FAILURE_JOB_BODY,
                },
            ]
        }

        def side_effect(job):
            if job["order_id"] == "KTnlBdi4M0PvK6jDTQK4gUTBP3PZY":
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
                    "body": REAL_SUCCESS_JOB_BODY,
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

    def test_lambda_handler_returns_batch_failure_for_malformed_json(self):
        event = {
            "Records": [
                {
                    "messageId": "msg-1",
                    "body": "{not-json",
                }
            ]
        }

        with patch("app.lambda_sqs_worker.process_webhook_job") as mock_worker:
            result = lambda_handler(event, context=None)

        mock_worker.assert_not_called()
        self.assertEqual(
            result,
            {"batchItemFailures": [{"itemIdentifier": "msg-1"}]},
        )
