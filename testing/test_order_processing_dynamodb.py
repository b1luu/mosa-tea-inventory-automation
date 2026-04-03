import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app import order_processing_dynamodb


def _conditional_check_failed():
    return ClientError(
        {
            "Error": {
                "Code": "ConditionalCheckFailedException",
                "Message": "conditional failed",
            }
        },
        "PutItem",
    )


class OrderProcessingDynamoDbTests(unittest.TestCase):
    def test_get_order_processing_state_returns_state_from_item(self):
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {
                "square_order_id": "order-1",
                "processing_state": "pending",
            }
        }

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            state = order_processing_dynamodb.get_order_processing_state("order-1")

        self.assertEqual(state, "pending")
        table.get_item.assert_called_once_with(
            Key={"square_order_id": "order-1"},
            ConsistentRead=True,
        )

    def test_reserve_order_processing_returns_false_on_conditional_failure(self):
        table = MagicMock()
        table.put_item.side_effect = _conditional_check_failed()

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            reserved = order_processing_dynamodb.reserve_order_processing("order-1")

        self.assertFalse(reserved)

    def test_clear_order_processing_reservation_returns_false_on_conditional_failure(self):
        table = MagicMock()
        error = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "conditional failed",
                }
            },
            "DeleteItem",
        )
        table.delete_item.side_effect = error

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            cleared = order_processing_dynamodb.clear_order_processing_reservation(
                "order-1"
            )

        self.assertFalse(cleared)

    def test_mark_order_applied_uses_pending_to_applied_transition(self):
        table = MagicMock()

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            transitioned = order_processing_dynamodb.mark_order_applied("order-1")

        self.assertTrue(transitioned)
        table.update_item.assert_called_once()
        kwargs = table.update_item.call_args.kwargs
        self.assertEqual(kwargs["Key"], {"square_order_id": "order-1"})
        self.assertEqual(kwargs["ConditionExpression"], "processing_state = :from_state")
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":from_state"],
            order_processing_dynamodb.PROCESSING_STATE_PROCESSING,
        )
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":to_state"],
            order_processing_dynamodb.PROCESSING_STATE_APPLIED,
        )

    def test_claim_order_processing_uses_pending_to_processing_transition(self):
        table = MagicMock()

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            transitioned = order_processing_dynamodb.claim_order_processing("order-1")

        self.assertTrue(transitioned)
        kwargs = table.update_item.call_args.kwargs
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":from_state"],
            order_processing_dynamodb.PROCESSING_STATE_PENDING,
        )
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":to_state"],
            order_processing_dynamodb.PROCESSING_STATE_PROCESSING,
        )

    def test_release_order_processing_claim_uses_processing_to_pending_transition(self):
        table = MagicMock()

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            transitioned = order_processing_dynamodb.release_order_processing_claim(
                "order-1"
            )

        self.assertTrue(transitioned)
        kwargs = table.update_item.call_args.kwargs
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":from_state"],
            order_processing_dynamodb.PROCESSING_STATE_PROCESSING,
        )
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":to_state"],
            order_processing_dynamodb.PROCESSING_STATE_PENDING,
        )

    def test_mark_order_failed_returns_false_when_order_is_not_pending(self):
        table = MagicMock()
        error = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "conditional failed",
                }
            },
            "UpdateItem",
        )
        table.update_item.side_effect = error

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            transitioned = order_processing_dynamodb.mark_order_failed("order-1")

        self.assertFalse(transitioned)

    def test_requeue_order_processing_tries_failed_then_blocked(self):
        table = MagicMock()

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            transitioned = order_processing_dynamodb.requeue_order_processing("order-1")

        self.assertTrue(transitioned)
        self.assertEqual(table.update_item.call_count, 1)
        kwargs = table.update_item.call_args.kwargs
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":from_state"],
            order_processing_dynamodb.PROCESSING_STATE_FAILED,
        )
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":to_state"],
            order_processing_dynamodb.PROCESSING_STATE_PENDING,
        )

    def test_requeue_order_processing_falls_back_to_blocked_transition(self):
        table = MagicMock()
        table.update_item.side_effect = [
            ClientError(
                {
                    "Error": {
                        "Code": "ConditionalCheckFailedException",
                        "Message": "conditional failed",
                    }
                },
                "UpdateItem",
            ),
            {},
        ]

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            transitioned = order_processing_dynamodb.requeue_order_processing("order-1")

        self.assertTrue(transitioned)
        self.assertEqual(table.update_item.call_count, 2)
        second_kwargs = table.update_item.call_args_list[1].kwargs
        self.assertEqual(
            second_kwargs["ExpressionAttributeValues"][":from_state"],
            order_processing_dynamodb.PROCESSING_STATE_BLOCKED,
        )

    def test_list_order_processing_rows_returns_sorted_rows(self):
        table = MagicMock()
        table.scan.return_value = {
            "Items": [
                {
                    "square_order_id": "order-1",
                    "processing_state": "pending",
                    "updated_at": "2026-04-01T01:00:00+00:00",
                },
                {
                    "square_order_id": "order-2",
                    "processing_state": "applied",
                    "applied_at": "2026-04-01T02:00:00+00:00",
                    "updated_at": "2026-04-01T02:00:00+00:00",
                },
            ]
        }

        with patch("app.order_processing_dynamodb._get_table", return_value=table):
            rows = order_processing_dynamodb.list_order_processing_rows()

        self.assertEqual(
            rows,
            [
                {
                    "square_order_id": "order-2",
                    "processing_state": "applied",
                    "applied_at": "2026-04-01T02:00:00+00:00",
                },
                {
                    "square_order_id": "order-1",
                    "processing_state": "pending",
                    "applied_at": None,
                },
            ],
        )
