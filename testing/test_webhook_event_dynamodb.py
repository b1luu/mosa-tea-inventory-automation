import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app import webhook_event_dynamodb


class WebhookEventDynamoDbTests(unittest.TestCase):
    def test_get_webhook_event_returns_item(self):
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {
                "event_id": "evt-1",
                "merchant_id": "merchant-1",
                "event_type": "order.updated",
                "status": "received",
                "received_at": "2026-04-01T00:00:00+00:00",
                "updated_at": "2026-04-01T00:00:00+00:00",
            }
        }

        with patch("app.webhook_event_dynamodb._get_table", return_value=table):
            event = webhook_event_dynamodb.get_webhook_event("evt-1")

        self.assertEqual(event["event_id"], "evt-1")
        self.assertEqual(event["status"], "received")
        table.get_item.assert_called_once_with(
            Key={"event_id": "evt-1"},
            ConsistentRead=True,
        )

    def test_upsert_webhook_event_updates_item(self):
        table = MagicMock()

        with patch("app.webhook_event_dynamodb._get_table", return_value=table):
            webhook_event_dynamodb.upsert_webhook_event(
                event_id="evt-1",
                merchant_id="merchant-1",
                event_type="order.updated",
                order_id="order-1",
                order_state="COMPLETED",
                status="received",
            )

        table.update_item.assert_called_once()
        kwargs = table.update_item.call_args.kwargs
        self.assertEqual(kwargs["Key"], {"event_id": "evt-1"})
        self.assertEqual(kwargs["ExpressionAttributeValues"][":order_id"], "order-1")
        self.assertEqual(kwargs["ExpressionAttributeValues"][":status"], "received")

    def test_create_webhook_event_uses_conditional_put(self):
        table = MagicMock()

        with patch("app.webhook_event_dynamodb._get_table", return_value=table):
            created = webhook_event_dynamodb.create_webhook_event(
                event_id="evt-1",
                merchant_id="merchant-1",
                event_type="order.updated",
                order_id="order-1",
                order_state="COMPLETED",
                status="received",
            )

        self.assertTrue(created)
        table.put_item.assert_called_once()
        kwargs = table.put_item.call_args.kwargs
        self.assertEqual(kwargs["Item"]["event_id"], "evt-1")
        self.assertEqual(kwargs["ConditionExpression"], "attribute_not_exists(event_id)")

    def test_create_webhook_event_returns_false_on_conditional_failure(self):
        table = MagicMock()
        table.put_item.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "conditional failed",
                }
            },
            "PutItem",
        )

        with patch("app.webhook_event_dynamodb._get_table", return_value=table):
            created = webhook_event_dynamodb.create_webhook_event(
                event_id="evt-1",
                merchant_id="merchant-1",
                event_type="order.updated",
            )

        self.assertFalse(created)

    def test_list_webhook_events_returns_sorted_rows(self):
        table = MagicMock()
        table.scan.return_value = {
            "Items": [
                {
                    "event_id": "evt-1",
                    "merchant_id": "merchant-1",
                    "event_type": "order.updated",
                    "status": "received",
                    "received_at": "2026-04-01T00:00:00+00:00",
                    "updated_at": "2026-04-01T00:00:00+00:00",
                },
                {
                    "event_id": "evt-2",
                    "merchant_id": "merchant-1",
                    "event_type": "order.created",
                    "status": "ignored",
                    "received_at": "2026-04-01T01:00:00+00:00",
                    "updated_at": "2026-04-01T01:00:00+00:00",
                },
            ]
        }

        with patch("app.webhook_event_dynamodb._get_table", return_value=table):
            rows = webhook_event_dynamodb.list_webhook_events()

        self.assertEqual(rows[0]["event_id"], "evt-2")
        self.assertEqual(rows[1]["event_id"], "evt-1")
