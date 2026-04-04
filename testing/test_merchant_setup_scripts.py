import json
import tempfile
import unittest
from pathlib import Path

from app import merchant_store, merchant_store_db
from app.json_utils import to_jsonable
from scripts.approve_merchant_catalog_binding import _parse_args as parse_approve_args
from scripts.enable_merchant_writes import _summarize_result
from scripts.enable_merchant_writes import _parse_args as parse_enable_args
from scripts.show_merchant_setup import build_report, _parse_args as parse_show_args
from scripts.upsert_merchant_catalog_binding import _parse_args as parse_upsert_args


class MerchantSetupScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = merchant_store_db.DB_FILE
        merchant_store_db.DB_FILE = Path(self.temp_dir.name) / "merchant_store.db"

    def tearDown(self):
        merchant_store_db.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_parse_show_args(self):
        environment, merchant_id = parse_show_args(
            ["--environment", "sandbox", "--merchant-id", "merchant-1"]
        )
        self.assertEqual(environment, "sandbox")
        self.assertEqual(merchant_id, "merchant-1")

    def test_parse_upsert_args(self):
        environment, merchant_id, location_id, version, mapping_file, notes = parse_upsert_args(
            [
                "--environment",
                "sandbox",
                "--merchant-id",
                "merchant-1",
                "--location-id",
                "LOC-1",
                "--version",
                "2",
                "--mapping-file",
                "/tmp/mapping.json",
                "--notes",
                "draft",
            ]
        )
        self.assertEqual(environment, "sandbox")
        self.assertEqual(merchant_id, "merchant-1")
        self.assertEqual(location_id, "LOC-1")
        self.assertEqual(version, 2)
        self.assertEqual(str(mapping_file), "/tmp/mapping.json")
        self.assertEqual(notes, "draft")

    def test_parse_approve_and_enable_args(self):
        self.assertEqual(
            parse_approve_args(
                [
                    "--environment",
                    "sandbox",
                    "--merchant-id",
                    "merchant-1",
                    "--location-id",
                    "LOC-1",
                    "--version",
                    "3",
                ]
            ),
            ("sandbox", "merchant-1", "LOC-1", 3),
        )
        self.assertEqual(
            parse_enable_args(
                [
                    "--environment",
                    "sandbox",
                    "--merchant-id",
                    "merchant-1",
                ]
            ),
            ("sandbox", "merchant-1"),
        )

    def test_build_report_includes_readiness_and_bindings(self):
        merchant_store.upsert_oauth_merchant(
            "sandbox",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
            display_name="Test Merchant",
            scopes=["ORDERS_READ", "INVENTORY_WRITE"],
        )
        merchant_store.upsert_catalog_binding(
            "sandbox",
            "merchant-1",
            "LOC-1",
            2,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY"}},
        )
        merchant_store.approve_catalog_binding("sandbox", "merchant-1", "LOC-1", 2)

        report = build_report("sandbox", "merchant-1")

        self.assertTrue(report["readiness"]["ready"])
        self.assertEqual(report["merchant"]["binding_version"], 2)
        self.assertEqual(len(report["bindings"]), 1)
        self.assertEqual(
            report["bindings"][0]["mapping"]["inventory_variation_ids"]["tgy"],
            "LIVE-TGY",
        )

    def test_enable_result_is_json_serializable(self):
        merchant_store.upsert_oauth_merchant(
            "sandbox",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
            display_name="Test Merchant",
            scopes=["ORDERS_READ", "INVENTORY_WRITE"],
        )
        merchant_store.upsert_catalog_binding(
            "sandbox",
            "merchant-1",
            "LOC-1",
            1,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY"}},
        )
        merchant_store.approve_catalog_binding("sandbox", "merchant-1", "LOC-1", 1)

        result = merchant_store.enable_merchant_writes_if_ready("sandbox", "merchant-1")
        rendered = json.dumps(to_jsonable(result))

        self.assertIn('"enabled": true', rendered)

    def test_enable_result_summary_redacts_tokens(self):
        merchant_store.upsert_oauth_merchant(
            "sandbox",
            "merchant-1",
            "access-1",
            refresh_token="refresh-1",
            selected_location_id="LOC-1",
            display_name="Test Merchant",
            scopes=["ORDERS_READ", "INVENTORY_WRITE"],
        )
        merchant_store.upsert_catalog_binding(
            "sandbox",
            "merchant-1",
            "LOC-1",
            1,
            {"inventory_variation_ids": {"tgy": "LIVE-TGY"}},
        )
        merchant_store.approve_catalog_binding("sandbox", "merchant-1", "LOC-1", 1)

        summary = _summarize_result(
            merchant_store.enable_merchant_writes_if_ready("sandbox", "merchant-1")
        )
        rendered = json.dumps(to_jsonable(summary))

        self.assertNotIn("access-1", rendered)
        self.assertNotIn("refresh-1", rendered)
        self.assertIn('"has_refresh_token": true', rendered)


if __name__ == "__main__":
    unittest.main()
