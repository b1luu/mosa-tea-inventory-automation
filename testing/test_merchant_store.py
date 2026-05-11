import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from app import merchant_store, merchant_store_db


class MerchantStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = merchant_store_db.DB_FILE
        merchant_store_db.DB_FILE = Path(self.temp_dir.name) / "merchant_store.db"
        self.store_mode_patcher = patch(
            "app.merchant_store.get_merchant_store_mode",
            return_value="sqlite",
        )
        self.store_mode_patcher.start()

    def tearDown(self):
        self.store_mode_patcher.stop()
        merchant_store_db.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_upsert_manual_merchant_creates_context_and_auth(self):
        context = merchant_store.upsert_manual_merchant(
            "production",
            "merchant-1",
            "access-1",
            selected_location_id="LOC-1",
            display_name="Store A",
            scopes=["ORDERS_READ", "INVENTORY_WRITE"],
        )

        self.assertEqual(context.environment, "production")
        self.assertEqual(context.merchant_id, "merchant-1")
        self.assertEqual(context.location_id, "LOC-1")
        self.assertFalse(context.writes_enabled)
        self.assertEqual(
            merchant_store.get_merchant_access_token("production", "merchant-1"),
            "access-1",
        )

    def test_enable_and_disable_merchant_writes_toggle_context(self):
        merchant_store.upsert_manual_merchant(
            "production",
            "merchant-1",
            "access-1",
        )

        self.assertTrue(merchant_store.enable_merchant_writes("production", "merchant-1"))
        self.assertTrue(
            merchant_store.get_merchant_context("production", "merchant-1").writes_enabled
        )

        self.assertTrue(merchant_store.disable_merchant_writes("production", "merchant-1"))
        self.assertFalse(
            merchant_store.get_merchant_context("production", "merchant-1").writes_enabled
        )

    def test_approve_catalog_binding_updates_active_binding_version(self):
        merchant_store.upsert_manual_merchant(
            "production",
            "merchant-1",
            "access-1",
            selected_location_id="LOC-1",
        )
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            2,
            {"inventory_variation_ids": {"tgy": "INV-2"}},
        )

        approved = merchant_store.approve_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            2,
        )

        self.assertTrue(approved)
        context = merchant_store.get_merchant_context("production", "merchant-1")
        self.assertEqual(context.binding_version, 2)
        binding = merchant_store.get_active_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
        )
        self.assertEqual(binding["version"], 2)

    def test_delete_merchant_removes_connection_auth_and_bindings(self):
        merchant_store.upsert_manual_merchant(
            "production",
            "merchant-1",
            "access-1",
            selected_location_id="LOC-1",
            display_name="Store A",
        )
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            1,
            {"inventory_variation_ids": {"tgy": "INV-1"}},
        )

        result = merchant_store.delete_merchant("production", "merchant-1")

        self.assertTrue(result["merchant_connection_deleted"])
        self.assertTrue(result["auth_deleted"])
        self.assertEqual(result["binding_count_deleted"], 1)
        self.assertIsNone(merchant_store.get_merchant_context("production", "merchant-1"))
        self.assertIsNone(merchant_store.get_merchant_auth_record("production", "merchant-1"))
        self.assertEqual(merchant_store.list_catalog_bindings("production", "merchant-1"), [])

    def test_refresh_oauth_merchant_access_token_persists_new_access_token(self):
        merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            expires_at="2026-04-01T00:00:00Z",
            scopes=["ORDERS_READ"],
        )
        token_response = type(
            "TokenResponse",
            (),
            {
                "access_token": "access-2",
                "refresh_token": "refresh-1",
                "merchant_id": "merchant-1",
                "token_type": "bearer",
                "expires_at": "2026-05-01T00:00:00Z",
                "short_lived": False,
            },
        )()
        fixed_now = datetime(2026, 4, 15, tzinfo=UTC)

        with (
            patch(
                "app.merchant_store.refresh_authorization_token",
                return_value=token_response,
            ) as mock_refresh,
            patch("app.merchant_store.datetime", wraps=datetime) as mock_datetime,
        ):
            mock_datetime.now.return_value = fixed_now
            refreshed = merchant_store.refresh_oauth_merchant_access_token(
                "production",
                "merchant-1",
                force=True,
            )
            resolved_access_token = merchant_store.resolve_merchant_access_token(
                "production",
                "merchant-1",
            )

        mock_refresh.assert_called_once_with("production", "refresh-1")
        self.assertEqual(refreshed["access_token"], "access-2")
        self.assertEqual(resolved_access_token, "access-2")

    def test_enable_merchant_writes_if_ready_refuses_missing_binding(self):
        merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
        )

        result = merchant_store.enable_merchant_writes_if_ready(
            "production",
            "merchant-1",
        )

        self.assertFalse(result["enabled"])
        self.assertIn("missing_approved_binding", result["readiness"]["reasons"])
        self.assertFalse(
            merchant_store.get_merchant_context("production", "merchant-1").writes_enabled
        )

    def test_enable_merchant_writes_if_ready_succeeds_after_binding_approval(self):
        merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
        )
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            2,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY"}},
        )
        merchant_store.approve_catalog_binding("production", "merchant-1", "LOC-1", 2)

        result = merchant_store.enable_merchant_writes_if_ready(
            "production",
            "merchant-1",
        )

        self.assertTrue(result["enabled"])
        self.assertTrue(result["readiness"]["ready"])
        self.assertTrue(
            merchant_store.get_merchant_context("production", "merchant-1").writes_enabled
        )

    def test_upsert_oauth_merchant_preserves_active_binding_version_for_selected_location(self):
        merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
        )
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            2,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY"}},
        )
        merchant_store.approve_catalog_binding("production", "merchant-1", "LOC-1", 2)

        context = merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-2",
            refresh_token="refresh-2",
            selected_location_id="LOC-1",
        )

        self.assertEqual(context.binding_version, 2)

    def test_set_selected_location_id_syncs_active_binding_version_for_new_location(self):
        merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
        )
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            1,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY-1"}},
        )
        merchant_store.approve_catalog_binding("production", "merchant-1", "LOC-1", 1)
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-2",
            2,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY-2"}},
        )
        merchant_store.approve_catalog_binding("production", "merchant-1", "LOC-2", 2)

        updated = merchant_store.set_selected_location_id(
            "production",
            "merchant-1",
            "LOC-2",
        )

        self.assertTrue(updated)
        context = merchant_store.get_merchant_context("production", "merchant-1")
        self.assertEqual(context.location_id, "LOC-2")
        self.assertEqual(context.binding_version, 2)

    def test_approve_catalog_binding_for_other_location_preserves_selected_location_binding(self):
        merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
        )
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            1,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY-1"}},
        )
        merchant_store.approve_catalog_binding("production", "merchant-1", "LOC-1", 1)
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-2",
            2,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY-2"}},
        )

        approved = merchant_store.approve_catalog_binding(
            "production",
            "merchant-1",
            "LOC-2",
            2,
        )

        self.assertTrue(approved)
        context = merchant_store.get_merchant_context("production", "merchant-1")
        self.assertEqual(context.location_id, "LOC-1")
        self.assertEqual(context.binding_version, 1)

    def test_upsert_approved_binding_for_other_location_preserves_selected_location_binding(self):
        merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
        )
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            1,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY-1"}},
        )
        merchant_store.approve_catalog_binding("production", "merchant-1", "LOC-1", 1)

        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-2",
            2,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY-2"}},
            status="approved",
        )

        context = merchant_store.get_merchant_context("production", "merchant-1")
        self.assertEqual(context.location_id, "LOC-1")
        self.assertEqual(context.binding_version, 1)

    def test_enable_merchant_writes_if_ready_backfills_missing_active_binding_version(self):
        merchant_store.upsert_oauth_merchant(
            "production",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
        )
        merchant_store.upsert_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            2,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY"}},
        )
        merchant_store.approve_catalog_binding("production", "merchant-1", "LOC-1", 2)
        merchant_store_db.set_active_binding_version("production", "merchant-1", None)

        result = merchant_store.enable_merchant_writes_if_ready(
            "production",
            "merchant-1",
        )

        self.assertTrue(result["enabled"])
        context = merchant_store.get_merchant_context("production", "merchant-1")
        self.assertEqual(context.binding_version, 2)
        self.assertTrue(context.writes_enabled)

    def test_get_merchant_context_uses_dynamodb_backend_when_configured(self):
        with (
            patch("app.merchant_store.get_merchant_store_mode", return_value="dynamodb"),
            patch(
                "app.merchant_store.merchant_store_dynamodb.get_merchant_connection",
                return_value={
                    "environment": "production",
                    "merchant_id": "merchant-9",
                    "status": "active",
                    "auth_mode": "oauth",
                    "display_name": "Prod Merchant",
                    "selected_location_id": "LOC-9",
                    "writes_enabled": True,
                    "active_binding_version": 3,
                },
            ),
        ):
            context = merchant_store.get_merchant_context("production", "merchant-9")

        self.assertEqual(context.merchant_id, "merchant-9")
        self.assertEqual(context.location_id, "LOC-9")
        self.assertTrue(context.writes_enabled)
        self.assertEqual(context.binding_version, 3)


if __name__ == "__main__":
    unittest.main()
