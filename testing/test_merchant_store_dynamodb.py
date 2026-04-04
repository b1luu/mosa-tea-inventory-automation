import json
import unittest
from unittest.mock import MagicMock, patch

from app import merchant_store_dynamodb


class MerchantStoreDynamoDbTests(unittest.TestCase):
    def test_get_merchant_connection_normalizes_dynamodb_item(self):
        table = MagicMock()
        table.get_item.return_value = {
            "Item": {
                "environment_merchant_id": "production#merchant-1",
                "environment": "production",
                "merchant_id": "merchant-1",
                "status": "active",
                "auth_mode": "oauth",
                "display_name": "Tea Shop",
                "selected_location_id": "LOC-1",
                "writes_enabled": True,
                "active_binding_version": 2,
                "created_at": "2026-04-04T00:00:00+00:00",
                "updated_at": "2026-04-04T00:01:00+00:00",
            }
        }

        with patch("app.merchant_store_dynamodb._get_connection_table", return_value=table):
            record = merchant_store_dynamodb.get_merchant_connection(
                "production",
                "merchant-1",
            )

        self.assertEqual(record["merchant_id"], "merchant-1")
        self.assertEqual(record["selected_location_id"], "LOC-1")
        self.assertTrue(record["writes_enabled"])
        self.assertEqual(record["active_binding_version"], 2)

    def test_get_merchant_auth_reads_secret_payload(self):
        client = MagicMock()
        client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "environment": "sandbox",
                    "merchant_id": "merchant-1",
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "token_type": "bearer",
                    "expires_at": "2026-05-01T00:00:00Z",
                    "short_lived": False,
                    "scopes": ["ORDERS_READ"],
                    "source": "oauth",
                    "created_at": "2026-04-04T00:00:00+00:00",
                    "updated_at": "2026-04-04T00:01:00+00:00",
                }
            )
        }

        with (
            patch(
                "app.merchant_store_dynamodb._create_secrets_manager_client",
                return_value=client,
            ),
            patch(
                "app.merchant_store_dynamodb.get_merchant_secret_prefix",
                return_value="mosa-tea/merchant-auth",
            ),
        ):
            record = merchant_store_dynamodb.get_merchant_auth("sandbox", "merchant-1")

        self.assertEqual(record["access_token"], "access-1")
        self.assertEqual(record["refresh_token"], "refresh-1")
        self.assertEqual(record["scopes"], ["ORDERS_READ"])

    def test_get_active_catalog_binding_returns_latest_approved_binding(self):
        table = MagicMock()
        table.query.return_value = {
            "Items": [
                {
                    "environment_merchant_location_id": "production#merchant-1#LOC-1",
                    "environment": "production",
                    "merchant_id": "merchant-1",
                    "location_id": "LOC-1",
                    "version": 3,
                    "status": "draft",
                    "mapping_json": json.dumps(
                        {"inventory_variation_ids": {"tgy": "INV-3"}}
                    ),
                    "created_at": "2026-04-04T00:00:00+00:00",
                    "updated_at": "2026-04-04T00:01:00+00:00",
                },
                {
                    "environment_merchant_location_id": "production#merchant-1#LOC-1",
                    "environment": "production",
                    "merchant_id": "merchant-1",
                    "location_id": "LOC-1",
                    "version": 2,
                    "status": "approved",
                    "mapping_json": json.dumps(
                        {"inventory_variation_ids": {"tgy": "INV-2"}}
                    ),
                    "approved_at": "2026-04-04T00:02:00+00:00",
                    "created_at": "2026-04-04T00:00:00+00:00",
                    "updated_at": "2026-04-04T00:02:00+00:00",
                },
            ]
        }

        with patch("app.merchant_store_dynamodb._get_binding_table", return_value=table):
            binding = merchant_store_dynamodb.get_active_catalog_binding(
                "production",
                "merchant-1",
                "LOC-1",
            )

        self.assertEqual(binding["version"], 2)
        self.assertEqual(binding["mapping"]["inventory_variation_ids"]["tgy"], "INV-2")


if __name__ == "__main__":
    unittest.main()
