import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import merchant_store_db
from scripts.migrate_local_merchant_state_to_cloud import (
    _parse_args,
    migrate_merchant_state,
)


class MigrateLocalMerchantStateToCloudTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = merchant_store_db.DB_FILE
        merchant_store_db.DB_FILE = Path(self.temp_dir.name) / "merchant_store.db"

    def tearDown(self):
        merchant_store_db.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_parse_args_supports_optional_sqlite_path_and_skip_secret_sync(self):
        environment, merchant_id, sqlite_db, skip_secret_sync = _parse_args(
            [
                "--environment",
                "sandbox",
                "--merchant-id",
                "merchant-1",
                "--sqlite-db",
                "/tmp/merchant_store.db",
                "--skip-secret-sync",
            ]
        )

        self.assertEqual(environment, "sandbox")
        self.assertEqual(merchant_id, "merchant-1")
        self.assertEqual(str(sqlite_db), "/tmp/merchant_store.db")
        self.assertTrue(skip_secret_sync)

    def test_migrate_merchant_state_copies_local_records_to_cloud_backend(self):
        merchant_store_db.upsert_merchant_connection(
            "sandbox",
            "merchant-1",
            status=merchant_store_db.MERCHANT_STATUS_ACTIVE,
            auth_mode=merchant_store_db.AUTH_SOURCE_OAUTH,
            display_name="Default Test Account",
            selected_location_id="LOC-1",
            writes_enabled=True,
            active_binding_version=2,
        )
        merchant_store_db.upsert_merchant_auth(
            "sandbox",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            token_type="bearer",
            expires_at="2026-05-01T00:00:00Z",
            short_lived=False,
            scopes=["ORDERS_READ", "INVENTORY_WRITE"],
            source=merchant_store_db.AUTH_SOURCE_OAUTH,
        )
        merchant_store_db.upsert_merchant_catalog_binding(
            "sandbox",
            "merchant-1",
            "LOC-1",
            2,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY"}},
            status=merchant_store_db.BINDING_STATUS_APPROVED,
            approved_at="2026-04-04T00:00:00Z",
        )

        cloud_connection = {
            "environment": "sandbox",
            "merchant_id": "merchant-1",
            "status": "active",
            "auth_mode": "oauth",
            "display_name": "Default Test Account",
            "selected_location_id": "LOC-1",
            "writes_enabled": True,
            "active_binding_version": 2,
        }
        cloud_auth = {
            "source": "oauth",
            "token_type": "bearer",
            "expires_at": "2026-05-01T00:00:00Z",
            "refresh_token": "refresh-1",
            "scopes": ["ORDERS_READ", "INVENTORY_WRITE"],
        }
        cloud_binding = {
            "environment": "sandbox",
            "merchant_id": "merchant-1",
            "location_id": "LOC-1",
            "version": 2,
            "status": "approved",
            "mapping": {"inventory_variation_ids": {"tgy": "LIVE-TGY"}},
        }

        with (
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.upsert_merchant_connection"
            ) as mock_upsert_connection,
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.upsert_merchant_auth"
            ) as mock_upsert_auth,
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.upsert_merchant_catalog_binding"
            ) as mock_upsert_binding,
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.set_active_binding_version"
            ) as mock_set_active_binding_version,
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.get_merchant_connection",
                return_value=cloud_connection,
            ),
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.get_merchant_auth",
                return_value=cloud_auth,
            ),
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.get_active_catalog_binding",
                return_value=cloud_binding,
            ),
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.list_merchant_catalog_bindings",
                return_value=[cloud_binding],
            ),
        ):
            result = migrate_merchant_state("sandbox", "merchant-1")

        mock_upsert_connection.assert_called_once()
        mock_upsert_auth.assert_called_once()
        mock_upsert_binding.assert_called_once()
        mock_set_active_binding_version.assert_called_once_with(
            "sandbox",
            "merchant-1",
            2,
        )
        self.assertTrue(result["secret_synced"])
        self.assertEqual(result["cloud"]["merchant"]["merchant_id"], "merchant-1")
        self.assertTrue(result["cloud"]["auth"]["has_refresh_token"])
        self.assertEqual(result["cloud"]["binding_count"], 1)

    def test_migrate_merchant_state_can_skip_secret_sync(self):
        merchant_store_db.upsert_merchant_connection(
            "sandbox",
            "merchant-1",
            status=merchant_store_db.MERCHANT_STATUS_ACTIVE,
            auth_mode=merchant_store_db.AUTH_SOURCE_OAUTH,
            selected_location_id="LOC-1",
        )

        with (
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.upsert_merchant_connection"
            ),
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.upsert_merchant_auth"
            ) as mock_upsert_auth,
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.get_merchant_connection",
                return_value={
                    "environment": "sandbox",
                    "merchant_id": "merchant-1",
                    "status": "active",
                    "auth_mode": "oauth",
                    "display_name": None,
                    "selected_location_id": "LOC-1",
                    "writes_enabled": False,
                    "active_binding_version": None,
                },
            ),
            patch(
                "scripts.migrate_local_merchant_state_to_cloud.merchant_store_dynamodb.list_merchant_catalog_bindings",
                return_value=[],
            ),
        ):
            result = migrate_merchant_state(
                "sandbox",
                "merchant-1",
                sync_secret=False,
            )

        mock_upsert_auth.assert_not_called()
        self.assertFalse(result["secret_synced"])


if __name__ == "__main__":
    unittest.main()
