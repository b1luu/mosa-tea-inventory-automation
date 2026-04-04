import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import merchant_store, merchant_store_db


class MerchantStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = merchant_store_db.DB_FILE
        merchant_store_db.DB_FILE = Path(self.temp_dir.name) / "merchant_store.db"

    def tearDown(self):
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

        with patch(
            "app.merchant_store.refresh_authorization_token",
            return_value=token_response,
        ) as mock_refresh:
            refreshed = merchant_store.refresh_oauth_merchant_access_token(
                "production",
                "merchant-1",
                force=True,
            )

        mock_refresh.assert_called_once_with("production", "refresh-1")
        self.assertEqual(refreshed["access_token"], "access-2")
        self.assertEqual(
            merchant_store.resolve_merchant_access_token("production", "merchant-1"),
            "access-2",
        )


if __name__ == "__main__":
    unittest.main()
