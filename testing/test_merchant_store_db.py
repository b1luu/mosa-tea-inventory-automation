import tempfile
import unittest
from pathlib import Path

from app import merchant_store_db


class MerchantStoreDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = merchant_store_db.DB_FILE
        merchant_store_db.DB_FILE = Path(self.temp_dir.name) / "merchant_store.db"

    def tearDown(self):
        merchant_store_db.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_upsert_and_fetch_merchant_connection(self):
        merchant_store_db.upsert_merchant_connection(
            "production",
            "merchant-1",
            status=merchant_store_db.MERCHANT_STATUS_ACTIVE,
            auth_mode=merchant_store_db.AUTH_SOURCE_MANUAL_TOKEN,
            display_name="M Tea",
            selected_location_id="LOC-1",
            writes_enabled=True,
            active_binding_version=3,
        )

        record = merchant_store_db.get_merchant_connection("production", "merchant-1")

        self.assertEqual(record["environment"], "production")
        self.assertEqual(record["merchant_id"], "merchant-1")
        self.assertEqual(record["status"], merchant_store_db.MERCHANT_STATUS_ACTIVE)
        self.assertEqual(record["auth_mode"], merchant_store_db.AUTH_SOURCE_MANUAL_TOKEN)
        self.assertEqual(record["display_name"], "M Tea")
        self.assertEqual(record["selected_location_id"], "LOC-1")
        self.assertTrue(record["writes_enabled"])
        self.assertEqual(record["active_binding_version"], 3)

    def test_merchant_auth_is_partitioned_by_environment(self):
        merchant_store_db.upsert_merchant_auth(
            "sandbox",
            "merchant-1",
            "sandbox-access",
            source=merchant_store_db.AUTH_SOURCE_MANUAL_TOKEN,
        )
        merchant_store_db.upsert_merchant_auth(
            "production",
            "merchant-1",
            "production-access",
            refresh_token="refresh-1",
            scopes=["ORDERS_READ"],
            source=merchant_store_db.AUTH_SOURCE_OAUTH,
        )

        sandbox_auth = merchant_store_db.get_merchant_auth("sandbox", "merchant-1")
        production_auth = merchant_store_db.get_merchant_auth("production", "merchant-1")

        self.assertEqual(sandbox_auth["access_token"], "sandbox-access")
        self.assertEqual(production_auth["access_token"], "production-access")
        self.assertEqual(production_auth["refresh_token"], "refresh-1")
        self.assertEqual(production_auth["scopes"], ["ORDERS_READ"])

    def test_get_active_catalog_binding_returns_latest_approved_version(self):
        merchant_store_db.upsert_merchant_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            1,
            {"inventory_variation_ids": {"tgy": "INV-1"}},
            status=merchant_store_db.BINDING_STATUS_APPROVED,
            approved_at="2026-04-03T20:00:00Z",
        )
        merchant_store_db.upsert_merchant_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            2,
            {"inventory_variation_ids": {"tgy": "INV-2"}},
            status=merchant_store_db.BINDING_STATUS_DRAFT,
        )
        merchant_store_db.upsert_merchant_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
            3,
            {"inventory_variation_ids": {"tgy": "INV-3"}},
            status=merchant_store_db.BINDING_STATUS_APPROVED,
            approved_at="2026-04-03T21:00:00Z",
        )

        binding = merchant_store_db.get_active_catalog_binding(
            "production",
            "merchant-1",
            "LOC-1",
        )

        self.assertEqual(binding["version"], 3)
        self.assertEqual(
            binding["mapping"]["inventory_variation_ids"]["tgy"],
            "INV-3",
        )

    def test_set_writes_enabled_updates_connection(self):
        merchant_store_db.upsert_merchant_connection(
            "production",
            "merchant-1",
            status=merchant_store_db.MERCHANT_STATUS_ACTIVE,
            auth_mode=merchant_store_db.AUTH_SOURCE_MANUAL_TOKEN,
        )

        updated = merchant_store_db.set_writes_enabled("production", "merchant-1", True)

        self.assertTrue(updated)
        self.assertTrue(
            merchant_store_db.get_merchant_connection("production", "merchant-1")[
                "writes_enabled"
            ]
        )


if __name__ == "__main__":
    unittest.main()
