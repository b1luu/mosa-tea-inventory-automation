import tempfile
import unittest
from pathlib import Path

from app import merchant_auth_db


class MerchantAuthDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = merchant_auth_db.DB_FILE
        merchant_auth_db.DB_FILE = Path(self.temp_dir.name) / "merchant_auth.db"

    def tearDown(self):
        merchant_auth_db.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_upsert_and_fetch_merchant_auth_record(self):
        merchant_auth_db.upsert_merchant_auth_record(
            merchant_id="merchant-1",
            access_token="access-1",
            refresh_token="refresh-1",
            token_type="bearer",
            expires_at="2026-04-01T00:00:00Z",
            short_lived=False,
            scopes=["ORDERS_READ", "INVENTORY_WRITE"],
        )

        record = merchant_auth_db.get_merchant_auth_record("merchant-1")

        self.assertIsNotNone(record)
        self.assertEqual(record["merchant_id"], "merchant-1")
        self.assertEqual(record["access_token"], "access-1")
        self.assertEqual(record["refresh_token"], "refresh-1")
        self.assertEqual(record["token_type"], "bearer")
        self.assertEqual(record["expires_at"], "2026-04-01T00:00:00Z")
        self.assertFalse(record["short_lived"])
        self.assertEqual(record["scopes"], ["ORDERS_READ", "INVENTORY_WRITE"])
        self.assertEqual(record["status"], merchant_auth_db.MERCHANT_STATUS_ACTIVE)

    def test_get_access_token_only_returns_active_records(self):
        merchant_auth_db.upsert_merchant_auth_record(
            merchant_id="merchant-2",
            access_token="access-2",
            refresh_token="refresh-2",
        )

        self.assertEqual(
            merchant_auth_db.get_merchant_access_token("merchant-2"),
            "access-2",
        )

        merchant_auth_db.mark_merchant_auth_revoked("merchant-2")

        self.assertIsNone(merchant_auth_db.get_merchant_access_token("merchant-2"))


if __name__ == "__main__":
    unittest.main()
