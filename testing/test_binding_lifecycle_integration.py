import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app import merchant_store, merchant_store_db
from scripts import (
    approve_merchant_catalog_binding,
    show_merchant_setup,
    upsert_merchant_catalog_binding,
)


class BindingLifecycleIntegrationTests(unittest.TestCase):
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

    def _seed_merchant(self, merchant_id, *, environment="production", location_id="LOC-1"):
        merchant_store.upsert_oauth_merchant(
            environment,
            merchant_id,
            f"{merchant_id}-access",
            refresh_token=f"{merchant_id}-refresh",
            selected_location_id=location_id,
            display_name=f"Merchant {merchant_id}",
            scopes=["ORDERS_READ", "INVENTORY_WRITE"],
        )

    def _write_mapping_file(self, filename, mapping=None):
        mapping_path = Path(self.temp_dir.name) / filename
        mapping_path.write_text(
            json.dumps(
                mapping
                or {
                    "sold_variation_aliases": {"PROD_ID": "SANDBOX_ID"},
                    "modifier_aliases": {},
                    "inventory_variation_ids": {"tgy": "LIVE_INV_VARIATION_ID"},
                }
            ),
            encoding="utf-8",
        )
        return mapping_path

    def _run_main(self, main_func, argv):
        stdout = StringIO()
        stderr = StringIO()
        with (
            patch.object(sys, "argv", argv),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = main_func()
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_upsert_then_approve_happy_path(self):
        self._seed_merchant("merchant-a")
        mapping_path = self._write_mapping_file("binding-v1.json")

        exit_code, stdout, stderr = self._run_main(
            upsert_merchant_catalog_binding.main,
            [
                "upsert_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "1",
                "--mapping-file",
                str(mapping_path),
            ],
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        upsert_payload = json.loads(stdout)
        self.assertEqual(upsert_payload["status"], "draft")
        self.assertEqual(upsert_payload["version"], 1)

        bindings = merchant_store.list_catalog_bindings(
            "production",
            "merchant-a",
            location_id="LOC-1",
        )
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["status"], "draft")

        exit_code, stdout, stderr = self._run_main(
            approve_merchant_catalog_binding.main,
            [
                "approve_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "1",
            ],
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        approve_payload = json.loads(stdout)
        self.assertTrue(approve_payload["approved"])
        self.assertEqual(approve_payload["binding_version_after"], 1)

        active_binding = merchant_store.get_active_catalog_binding(
            "production",
            "merchant-a",
            "LOC-1",
        )
        self.assertIsNotNone(active_binding)
        self.assertEqual(active_binding["version"], 1)
        self.assertEqual(active_binding["status"], "approved")
        self.assertEqual(
            active_binding["mapping"]["inventory_variation_ids"]["tgy"],
            "LIVE_INV_VARIATION_ID",
        )

    def test_version_progression_keeps_active_until_new_approval(self):
        self._seed_merchant("merchant-a")
        v1_mapping_path = self._write_mapping_file(
            "binding-v1.json",
            {
                "sold_variation_aliases": {"PROD_V1": "SANDBOX_V1"},
                "modifier_aliases": {},
                "inventory_variation_ids": {"tgy": "LIVE_INV_VARIATION_V1"},
            },
        )
        v2_mapping_path = self._write_mapping_file(
            "binding-v2.json",
            {
                "sold_variation_aliases": {"PROD_V2": "SANDBOX_V2"},
                "modifier_aliases": {},
                "inventory_variation_ids": {"tgy": "LIVE_INV_VARIATION_V2"},
            },
        )

        self._run_main(
            upsert_merchant_catalog_binding.main,
            [
                "upsert_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "1",
                "--mapping-file",
                str(v1_mapping_path),
            ],
        )
        self._run_main(
            approve_merchant_catalog_binding.main,
            [
                "approve_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "1",
            ],
        )

        active_binding = merchant_store.get_active_catalog_binding(
            "production",
            "merchant-a",
            "LOC-1",
        )
        self.assertEqual(active_binding["version"], 1)

        self._run_main(
            upsert_merchant_catalog_binding.main,
            [
                "upsert_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "2",
                "--mapping-file",
                str(v2_mapping_path),
            ],
        )

        active_binding = merchant_store.get_active_catalog_binding(
            "production",
            "merchant-a",
            "LOC-1",
        )
        self.assertEqual(active_binding["version"], 1)

        bindings = {
            binding["version"]: binding
            for binding in merchant_store.list_catalog_bindings(
                "production",
                "merchant-a",
                location_id="LOC-1",
            )
        }
        self.assertEqual(bindings[1]["status"], "approved")
        self.assertEqual(bindings[2]["status"], "draft")

        self._run_main(
            approve_merchant_catalog_binding.main,
            [
                "approve_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "2",
            ],
        )

        active_binding = merchant_store.get_active_catalog_binding(
            "production",
            "merchant-a",
            "LOC-1",
        )
        self.assertEqual(active_binding["version"], 2)
        self.assertEqual(
            active_binding["mapping"]["inventory_variation_ids"]["tgy"],
            "LIVE_INV_VARIATION_V2",
        )

    def test_approve_missing_binding_fails_cleanly(self):
        self._seed_merchant("merchant-a")

        exit_code, stdout, stderr = self._run_main(
            approve_merchant_catalog_binding.main,
            [
                "approve_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "99",
            ],
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Could not approve catalog binding", stderr)
        payload = json.loads(stdout)
        self.assertFalse(payload["approved"])
        self.assertIsNone(payload["active_binding"])
        self.assertIsNone(
            merchant_store.get_active_catalog_binding("production", "merchant-a", "LOC-1")
        )

    def test_upsert_without_approve_leaves_no_active_binding(self):
        self._seed_merchant("merchant-a")
        mapping_path = self._write_mapping_file("binding-v1.json")

        exit_code, stdout, stderr = self._run_main(
            upsert_merchant_catalog_binding.main,
            [
                "upsert_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "1",
                "--mapping-file",
                str(mapping_path),
            ],
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIsNone(
            merchant_store.get_active_catalog_binding("production", "merchant-a", "LOC-1")
        )
        bindings = merchant_store.list_catalog_bindings(
            "production",
            "merchant-a",
            location_id="LOC-1",
        )
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["version"], 1)
        self.assertEqual(bindings[0]["status"], "draft")
        self.assertEqual(json.loads(stdout)["status"], "draft")

    def test_per_merchant_isolation(self):
        self._seed_merchant("merchant-a", location_id="LOC-A")
        self._seed_merchant("merchant-b", location_id="LOC-B")
        mapping_path = self._write_mapping_file("binding-a.json")

        self._run_main(
            upsert_merchant_catalog_binding.main,
            [
                "upsert_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-A",
                "--version",
                "1",
                "--mapping-file",
                str(mapping_path),
            ],
        )
        self._run_main(
            approve_merchant_catalog_binding.main,
            [
                "approve_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-A",
                "--version",
                "1",
            ],
        )

        active_binding_a = merchant_store.get_active_catalog_binding(
            "production",
            "merchant-a",
            "LOC-A",
        )
        active_binding_b = merchant_store.get_active_catalog_binding(
            "production",
            "merchant-b",
            "LOC-B",
        )

        self.assertIsNotNone(active_binding_a)
        self.assertEqual(active_binding_a["merchant_id"], "merchant-a")
        self.assertEqual(
            active_binding_a["mapping"]["inventory_variation_ids"]["tgy"],
            "LIVE_INV_VARIATION_ID",
        )
        self.assertIsNone(active_binding_b)
        self.assertEqual(
            merchant_store.list_catalog_bindings(
                "production",
                "merchant-b",
                location_id="LOC-B",
            ),
            [],
        )

    def test_show_merchant_setup_reflects_lifecycle_state(self):
        self._seed_merchant("merchant-a")
        mapping_path = self._write_mapping_file("binding-v1.json")

        self._run_main(
            upsert_merchant_catalog_binding.main,
            [
                "upsert_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "1",
                "--mapping-file",
                str(mapping_path),
            ],
        )
        self._run_main(
            approve_merchant_catalog_binding.main,
            [
                "approve_merchant_catalog_binding.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
                "--location-id",
                "LOC-1",
                "--version",
                "1",
            ],
        )

        exit_code, stdout, stderr = self._run_main(
            show_merchant_setup.main,
            [
                "show_merchant_setup.py",
                "--environment",
                "production",
                "--merchant-id",
                "merchant-a",
            ],
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["merchant"]["status"], "active")
        self.assertEqual(payload["merchant"]["binding_version"], 1)
        self.assertEqual(payload["active_binding"]["status"], "approved")
        self.assertEqual(payload["active_binding"]["version"], 1)


if __name__ == "__main__":
    unittest.main()
