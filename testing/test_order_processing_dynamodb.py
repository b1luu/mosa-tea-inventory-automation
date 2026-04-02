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
            order_processing_dynamodb.PROCESSING_STATE_PENDING,
        )
        self.assertEqual(
            kwargs["ExpressionAttributeValues"][":to_state"],
            order_processing_dynamodb.PROCESSING_STATE_APPLIED,
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
