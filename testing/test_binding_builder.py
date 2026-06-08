import json
import unittest
from pathlib import Path

from app.binding_builder import build_binding_from_catalogs
from app.binding_coverage_report import classify_binding_coverage


def _variation(item_name, variation_name="Regular"):
    return {
        "item_name": item_name,
        "variation_name": variation_name,
        "sellable": True,
        "stockable": True,
    }


def _modifier(name):
    return {"name": name, "modifier_list_id": "ml-1"}


class BindingBuilderTests(unittest.TestCase):
    def _canonical(self):
        return {
            "variations": {
                "CANON-DRINK": _variation("TGY Special"),
                "CANON-INV": _variation("TGY"),
                "CANON-UNTRACKED": _variation("Mystery Soda"),
            },
            "modifiers": {
                "CANON-SUGAR-100": _modifier("100% Sugar"),
                "CANON-ICE": _modifier("No Ice"),
            },
        }

    def _targets(self):
        # CANON-DRINK is a recipe drink, CANON-INV backs inventory key "tgy",
        # CANON-SUGAR-100 is recipe-relevant; ice and Mystery Soda are not.
        return {
            "sold_variation_ids": {"CANON-DRINK"},
            "modifier_ids": {"CANON-SUGAR-100"},
            "inventory_keys": {"tgy"},
        }

    def _inventory_item_map(self):
        return {"tgy": {"square_variation_id": "CANON-INV", "name": "TGY", "unit": "g"}}

    def test_name_match_routes_sold_inventory_and_modifier(self):
        target = {
            "variations": {
                "LIVE-1": _variation("TGY Special"),   # sold
                "LIVE-2": _variation("TGY"),            # inventory
                "LIVE-3": _variation("Mystery Soda"),   # matches a non-target -> unmapped
                "LIVE-4": _variation("Gift Card"),      # no match -> unmapped
            },
            "modifiers": {
                "LIVE-M1": _modifier("100% Sugar"),     # modifier alias
                "LIVE-M2": _modifier("No Ice"),         # not a target -> unmapped
            },
        }

        result = build_binding_from_catalogs(
            target,
            self._canonical(),
            canonical_targets=self._targets(),
            inventory_item_map=self._inventory_item_map(),
        )
        mapping = result["mapping"]

        self.assertEqual(mapping["sold_variation_aliases"], {"LIVE-1": "CANON-DRINK"})
        self.assertEqual(mapping["inventory_variation_ids"], {"tgy": "LIVE-2"})
        self.assertEqual(mapping["modifier_aliases"], {"LIVE-M1": "CANON-SUGAR-100"})

        unmapped_ids = {
            entry["live_id"]
            for entry in result["match_report"]["sold"]["unmapped_live_variations"]
        }
        self.assertEqual(unmapped_ids, {"LIVE-3", "LIVE-4"})
        unmapped_mods = {
            entry["live_id"]
            for entry in result["match_report"]["modifiers"]["unmapped_live_modifiers"]
        }
        self.assertEqual(unmapped_mods, {"LIVE-M2"})

    def test_normalization_tolerates_whitespace_and_case(self):
        target = {
            "variations": {"LIVE-1": _variation("  tgy  special ")},
            "modifiers": {"LIVE-M1": _modifier("100%  SUGAR")},
        }
        result = build_binding_from_catalogs(
            target,
            self._canonical(),
            canonical_targets=self._targets(),
            inventory_item_map=self._inventory_item_map(),
        )
        self.assertEqual(
            result["mapping"]["sold_variation_aliases"], {"LIVE-1": "CANON-DRINK"}
        )
        self.assertEqual(
            result["mapping"]["modifier_aliases"], {"LIVE-M1": "CANON-SUGAR-100"}
        )

    def test_regular_variation_name_matches_empty_canonical(self):
        # Square's dashboard auto-assigns variation_name='Regular' when an item
        # has one variation; API-built canonicals often leave the field blank.
        # Both forms semantically mean "the sole variation," so they must match.
        canonical_with_blank = {
            "variations": {"CANON-DRINK": _variation("TGY Special", variation_name=None)},
            "modifiers": {},
        }
        target_with_regular = {
            "variations": {"LIVE-1": _variation("TGY Special", variation_name="Regular")},
            "modifiers": {},
        }
        result = build_binding_from_catalogs(
            target_with_regular,
            canonical_with_blank,
            canonical_targets=self._targets(),
            inventory_item_map=self._inventory_item_map(),
        )
        self.assertEqual(result["mapping"]["sold_variation_aliases"], {"LIVE-1": "CANON-DRINK"})

    def test_renamed_drink_becomes_unmapped_not_misrouted(self):
        # A rename must fail safe (unmapped), never silently map to the wrong id.
        target = {"variations": {"LIVE-1": _variation("TGY Spesh")}, "modifiers": {}}
        result = build_binding_from_catalogs(
            target,
            self._canonical(),
            canonical_targets=self._targets(),
            inventory_item_map=self._inventory_item_map(),
        )
        self.assertEqual(result["mapping"]["sold_variation_aliases"], {})
        self.assertEqual(
            result["match_report"]["sold"]["unmapped_live_variations"][0]["live_id"],
            "LIVE-1",
        )

    def test_missing_inventory_key_is_reported(self):
        target = {"variations": {"LIVE-1": _variation("TGY Special")}, "modifiers": {}}
        result = build_binding_from_catalogs(
            target,
            self._canonical(),
            canonical_targets=self._targets(),
            inventory_item_map=self._inventory_item_map(),
        )
        self.assertEqual(result["match_report"]["inventory"]["missing_keys"], ["tgy"])


class BindingBuilderFixtureIntegrationTests(unittest.TestCase):
    """End-to-end against the committed demo fixtures: a derived binding must
    pass the real coverage gate with zero blocking issues."""

    def setUp(self):
        base = Path("testing/fixtures/catalog")
        self.canonical = json.loads((base / "sandbox_canonical_catalog.json").read_text())
        self.simulated = json.loads(
            (base / "simulated_production_catalog.json").read_text()
        )

    def test_simulated_catalog_yields_approvable_binding(self):
        result = build_binding_from_catalogs(self.simulated, self.canonical)
        binding = {"location_id": "SIM", "version": 1, "mapping": result["mapping"]}

        coverage = classify_binding_coverage(binding, self.simulated)

        self.assertEqual(coverage["summary"]["blocking_issue_count"], 0)
        self.assertTrue(coverage["summary"]["ready_for_approval"])
        # The simulated catalog includes one extra sellable item with no recipe.
        self.assertGreaterEqual(coverage["summary"]["warning_count"], 1)


if __name__ == "__main__":
    unittest.main()
