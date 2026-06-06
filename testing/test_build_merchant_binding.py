import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_merchant_binding import build_merchant_binding


class BuildMerchantBindingTests(unittest.TestCase):
    """The script is a thin orchestrator over functions tested elsewhere
    (build_binding_from_catalogs, _load_live_catalog_snapshot). These tests
    just verify the orchestration: canonical file is loaded, the live snapshot
    function is called, the mapping comes back in the expected shape, and
    a missing canonical file fails fast."""

    def test_returns_mapping_when_inputs_present(self):
        canonical = {
            "variations": {
                "CANON_LATTE": {
                    "id": "CANON_LATTE",
                    "item_name": "Latte",
                    "variation_name": "Regular",
                    "sellable": True,
                    "stockable": False,
                }
            },
            "modifiers": {},
        }
        live_catalog = {
            "variations": {
                "LIVE_LATTE": {
                    "id": "LIVE_LATTE",
                    "item_name": "Latte",
                    "variation_name": "Regular",
                    "sellable": True,
                    "stockable": False,
                }
            },
            "modifiers": {},
        }

        # Stub out the canonical_targets so the matched item lands in sold_variation_aliases
        with tempfile.TemporaryDirectory() as tmpdir:
            canonical_path = Path(tmpdir) / "canonical.json"
            canonical_path.write_text(json.dumps(canonical))

            with patch(
                "scripts.build_merchant_binding._load_live_catalog_snapshot",
                return_value=live_catalog,
            ) as mock_load, patch(
                "scripts.build_merchant_binding.build_binding_from_catalogs",
                return_value={
                    "mapping": {
                        "sold_variation_aliases": {"LIVE_LATTE": "CANON_LATTE"},
                        "modifier_aliases": {},
                        "inventory_variation_ids": {},
                        "ignored_live_variation_ids": [],
                    },
                    "match_report": {
                        "sold": {
                            "matched": [{"live_id": "LIVE_LATTE"}],
                            "unmapped_live_variations": [],
                            "ambiguous": [],
                        },
                        "inventory": {"matched": [], "missing_keys": []},
                        "modifiers": {"matched": [], "unmapped_live_modifiers": []},
                    },
                },
            ) as mock_build:
                mapping, report, live = build_merchant_binding(
                    "sandbox", "ML123", canonical_path
                )

        mock_load.assert_called_once_with("sandbox", "ML123")
        mock_build.assert_called_once()
        # The canonical passed to the builder matches the file we wrote
        args, _ = mock_build.call_args
        self.assertEqual(args[0], live_catalog)
        self.assertEqual(args[1], canonical)
        self.assertEqual(mapping["sold_variation_aliases"], {"LIVE_LATTE": "CANON_LATTE"})
        self.assertEqual(report["sold"]["matched"][0]["live_id"], "LIVE_LATTE")

    def test_raises_when_canonical_file_missing(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            build_merchant_binding("sandbox", "ML123", Path("/nonexistent/file.json"))
        self.assertIn("Canonical catalog file not found", str(ctx.exception))

    def test_mapping_shape_matches_upsert_input(self):
        # Sanity check: the keys we expose are exactly what
        # scripts/upsert_merchant_catalog_binding.py passes through to
        # app.merchant_store.upsert_catalog_binding.
        canonical = {"variations": {}, "modifiers": {}}
        with tempfile.TemporaryDirectory() as tmpdir:
            canonical_path = Path(tmpdir) / "canonical.json"
            canonical_path.write_text(json.dumps(canonical))

            with patch(
                "scripts.build_merchant_binding._load_live_catalog_snapshot",
                return_value={"variations": {}, "modifiers": {}},
            ):
                mapping, _, _ = build_merchant_binding(
                    "sandbox", "ML123", canonical_path
                )

        expected_keys = {
            "sold_variation_aliases",
            "modifier_aliases",
            "inventory_variation_ids",
            "ignored_live_variation_ids",
        }
        self.assertEqual(set(mapping.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main()
