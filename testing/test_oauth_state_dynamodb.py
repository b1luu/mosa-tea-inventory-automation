import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app import oauth_state_dynamodb


class OAuthStateDynamoDbTests(unittest.TestCase):
    def test_create_oauth_state_writes_conditional_item(self):
        table = MagicMock()
        now = datetime(2026, 5, 9, tzinfo=UTC)

        with (
            patch("app.oauth_state_dynamodb._get_table", return_value=table),
            patch("app.oauth_state_dynamodb._utcnow", return_value=now),
            patch(
                "app.oauth_state_dynamodb.uuid.uuid4",
                return_value=UUID("12345678-1234-5678-1234-567812345678"),
            ),
            patch("app.oauth_state_dynamodb.get_oauth_state_max_age_seconds", return_value=600),
        ):
            state = oauth_state_dynamodb.create_oauth_state("sandbox")

        self.assertEqual(state, "12345678-1234-5678-1234-567812345678")
        table.put_item.assert_called_once_with(
            Item={
                "state": "12345678-1234-5678-1234-567812345678",
                "environment": "sandbox",
                "created_at": now.isoformat(),
                "expires_at_epoch": int((now + timedelta(seconds=600)).timestamp()),
            },
            ConditionExpression="attribute_not_exists(#state)",
            ExpressionAttributeNames={"#state": "state"},
        )

    def test_consume_oauth_state_reads_and_marks_unconsumed_item(self):
        table = MagicMock()
        created_at = datetime(2026, 5, 9, 19, 0, tzinfo=UTC)
        consumed_at = datetime(2026, 5, 9, 19, 5, tzinfo=UTC)
        table.get_item.return_value = {
            "Item": {
                "state": "state-123",
                "environment": "production",
                "created_at": created_at.isoformat(),
                "expires_at_epoch": int(
                    (created_at + timedelta(seconds=600)).timestamp()
                ),
            }
        }

        with (
            patch("app.oauth_state_dynamodb._get_table", return_value=table),
            patch("app.oauth_state_dynamodb._utcnow", return_value=consumed_at),
        ):
            record = oauth_state_dynamodb.consume_oauth_state(
                "state-123",
                max_age_seconds=600,
            )

        self.assertEqual(record["state"], "state-123")
        self.assertEqual(record["environment"], "production")
        table.get_item.assert_called_once_with(
            Key={"state": "state-123"},
            ConsistentRead=True,
        )
        table.update_item.assert_called_once_with(
            Key={"state": "state-123"},
            UpdateExpression="SET consumed_at = :consumed_at",
            ConditionExpression=(
                "attribute_exists(#state) AND "
                "attribute_not_exists(consumed_at) AND "
                "expires_at_epoch >= :now_epoch"
            ),
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={
                ":consumed_at": consumed_at.isoformat(),
                ":now_epoch": int(consumed_at.timestamp()),
            },
        )

    def test_consume_oauth_state_returns_none_when_item_missing(self):
        table = MagicMock()
        table.get_item.return_value = {}

        with patch("app.oauth_state_dynamodb._get_table", return_value=table):
            record = oauth_state_dynamodb.consume_oauth_state("missing-state")

        self.assertIsNone(record)
        table.update_item.assert_not_called()

    def test_consume_oauth_state_returns_none_when_item_already_consumed(self):
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {
                "state": "state-123",
                "environment": "production",
                "created_at": datetime(2026, 5, 9, 19, 0, tzinfo=UTC).isoformat(),
                "consumed_at": datetime(2026, 5, 9, 19, 1, tzinfo=UTC).isoformat(),
            }
        }

        with patch("app.oauth_state_dynamodb._get_table", return_value=table):
            record = oauth_state_dynamodb.consume_oauth_state("state-123")

        self.assertIsNone(record)
        table.update_item.assert_not_called()

    def test_consume_oauth_state_returns_none_when_item_expired(self):
        table = MagicMock()
        created_at = datetime(2026, 5, 9, 19, 0, tzinfo=UTC)
        now = created_at + timedelta(minutes=30)
        table.get_item.return_value = {
            "Item": {
                "state": "state-123",
                "environment": "production",
                "created_at": created_at.isoformat(),
                "expires_at_epoch": int(created_at.timestamp()),
            }
        }

        with (
            patch("app.oauth_state_dynamodb._get_table", return_value=table),
            patch("app.oauth_state_dynamodb._utcnow", return_value=now),
        ):
            record = oauth_state_dynamodb.consume_oauth_state(
                "state-123",
                max_age_seconds=60,
            )

        self.assertIsNone(record)
        table.update_item.assert_not_called()

    def test_consume_oauth_state_returns_none_on_conditional_update_failure(self):
        table = MagicMock()
        created_at = datetime(2026, 5, 9, 19, 0, tzinfo=UTC)
        now = datetime(2026, 5, 9, 19, 5, tzinfo=UTC)
        table.get_item.return_value = {
            "Item": {
                "state": "state-123",
                "environment": "production",
                "created_at": created_at.isoformat(),
                "expires_at_epoch": int(
                    (created_at + timedelta(seconds=600)).timestamp()
                ),
            }
        }
        table.update_item.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "conditional failed",
                }
            },
            "UpdateItem",
        )

        with (
            patch("app.oauth_state_dynamodb._get_table", return_value=table),
            patch("app.oauth_state_dynamodb._utcnow", return_value=now),
        ):
            record = oauth_state_dynamodb.consume_oauth_state("state-123")

        self.assertIsNone(record)

    def test_create_oauth_state_raises_after_bounded_collision_retries(self):
        table = MagicMock()
        now = datetime(2026, 5, 9, tzinfo=UTC)
        table.put_item.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ConditionalCheckFailedException",
                    "Message": "conditional failed",
                }
            },
            "PutItem",
        )

        with (
            patch("app.oauth_state_dynamodb._get_table", return_value=table),
            patch("app.oauth_state_dynamodb._utcnow", return_value=now),
            patch(
                "app.oauth_state_dynamodb.uuid.uuid4",
                side_effect=[
                    UUID("12345678-1234-5678-1234-567812345678"),
                    UUID("22345678-1234-5678-1234-567812345678"),
                    UUID("32345678-1234-5678-1234-567812345678"),
                ],
            ),
            patch("app.oauth_state_dynamodb.get_oauth_state_max_age_seconds", return_value=600),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Unable to allocate a unique OAuth state after 3 attempts.",
            ):
                oauth_state_dynamodb.create_oauth_state("sandbox")

        self.assertEqual(table.put_item.call_count, 3)

    def test_consume_oauth_state_uses_created_at_guard_for_legacy_rows(self):
        table = MagicMock()
        created_at = datetime(2026, 5, 9, 19, 0, tzinfo=UTC)
        now = datetime(2026, 5, 9, 19, 5, tzinfo=UTC)
        table.get_item.return_value = {
            "Item": {
                "state": "state-123",
                "environment": "production",
                "created_at": created_at.isoformat(),
            }
        }

        with (
            patch("app.oauth_state_dynamodb._get_table", return_value=table),
            patch("app.oauth_state_dynamodb._utcnow", return_value=now),
        ):
            record = oauth_state_dynamodb.consume_oauth_state(
                "state-123",
                max_age_seconds=600,
            )

        self.assertEqual(record["state"], "state-123")
        table.update_item.assert_called_once_with(
            Key={"state": "state-123"},
            UpdateExpression="SET consumed_at = :consumed_at",
            ConditionExpression=(
                "attribute_exists(#state) AND "
                "attribute_not_exists(consumed_at) AND "
                "created_at >= :min_created_at"
            ),
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={
                ":consumed_at": now.isoformat(),
                ":min_created_at": (now - timedelta(seconds=600)).isoformat(),
            },
        )


if __name__ == "__main__":
    unittest.main()
