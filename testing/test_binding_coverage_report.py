import unittest
from unittest.mock import patch

from app.binding_coverage_report import build_binding_coverage_report
from app.merchant_store import MerchantContext


def _variation(variation_id, *, item_name, variation_name, sellable=True, stockable=True):
    return type(
        "Variation",
        (),
        {
            "id": variation_id,
            "name": variation_name,
            "item_variation_data": type(
                "VariationData",
                (),
                {
                    "name": variation_name,
                    "sellable": sellable,
                    "stockable": stockable,
                },
            )(),
        },
    )()


def _item(item_name, *variations):
    return type(
        "Item",
        (),
        {
            "item_data": type(
                "ItemData",
                (),
                {
                    "name": item_name,
                    "variations": list(variations),
                },
            )(),
        },
    )()


def _modifier(modifier_id, *, name, modifier_list_id="LIST-1"):
    return type(
        "Modifier",
        (),
        {
            "id": modifier_id,
            "name": name,
            "modifier_data": type(
                "ModifierData",
                (),
                {
                    "name": name,
                    "modifier_list_id": modifier_list_id,
                },
            )(),
        },
    )()


class _FakeCatalog:
    def __init__(self, items, modifiers):
        self._items = items
        self._modifiers = modifiers

    def list(self, *, types):
        if types == "ITEM":
            return list(self._items)
        if types == "MODIFIER":
            return list(self._modifiers)
        raise AssertionError(types)


class _FakeClient:
    def __init__(self, items, modifiers):
        self.catalog = _FakeCatalog(items, modifiers)


class BindingCoverageReportTests(unittest.TestCase):
    def test_ignored_live_variation_is_visible_but_not_actionable(self):
        binding = {
            "location_id": "LOC-1",
            "version": 3,
            "status": "draft",
            "mapping": {
                "sold_variation_aliases": {"LIVE-SOLD-1": "CANONICAL-SOLD-1"},
                "modifier_aliases": {},
                "inventory_variation_ids": {},
                "ignored_live_variation_ids": ["IGNORED-LIVE-SOLD"],
            },
        }
        client = _FakeClient(
            [
                _item(
                    "Tea",
                    _variation("LIVE-SOLD-1", item_name="Tea", variation_name="Regular"),
                    _variation(
                        "IGNORED-LIVE-SOLD",
                        item_name="Rewards",
                        variation_name="Free Drink (100 Reward)",
                    ),
                )
            ],
            [],
        )

        with (
            patch("app.binding_coverage_report.get_merchant_context", return_value=None),
            patch("app.binding_coverage_report.list_catalog_bindings", return_value=[binding]),
            patch("app.binding_coverage_report.get_active_catalog_binding", return_value=binding),
            patch(
                "app.binding_coverage_report.get_canonical_binding_targets",
                return_value={
                    "sold_variation_ids": {"CANONICAL-SOLD-1"},
                    "modifier_ids": set(),
                    "inventory_keys": set(),
                },
            ),
            patch(
                "app.binding_coverage_report.create_square_client_for_merchant",
                return_value=client,
            ),
        ):
            report = build_binding_coverage_report("production", "merchant-1", "LOC-1")

        self.assertEqual(
            [variation["id"] for variation in report["sold_variations"]["ignored_live_variations"]],
            ["IGNORED-LIVE-SOLD"],
        )
        self.assertEqual(report["sold_variations"]["unmapped_live_variations"], [])
        self.assertEqual(report["summary"]["warning_count"], 0)

    def test_missing_ignore_list_keeps_unmapped_variation_behavior(self):
        binding = {
            "location_id": "LOC-1",
            "version": 3,
            "status": "draft",
            "mapping": {
                "sold_variation_aliases": {"LIVE-SOLD-1": "CANONICAL-SOLD-1"},
                "modifier_aliases": {},
                "inventory_variation_ids": {},
            },
        }
        client = _FakeClient(
            [
                _item(
                    "Tea",
                    _variation("LIVE-SOLD-1", item_name="Tea", variation_name="Regular"),
                    _variation("UNMAPPED-LIVE-SOLD", item_name="Tea", variation_name="Large"),
                )
            ],
            [],
        )

        with (
            patch("app.binding_coverage_report.get_merchant_context", return_value=None),
            patch("app.binding_coverage_report.list_catalog_bindings", return_value=[binding]),
            patch("app.binding_coverage_report.get_active_catalog_binding", return_value=binding),
            patch(
                "app.binding_coverage_report.get_canonical_binding_targets",
                return_value={
                    "sold_variation_ids": {"CANONICAL-SOLD-1"},
                    "modifier_ids": set(),
                    "inventory_keys": set(),
                },
            ),
            patch(
                "app.binding_coverage_report.create_square_client_for_merchant",
                return_value=client,
            ),
        ):
            report = build_binding_coverage_report("production", "merchant-1", "LOC-1")

        self.assertEqual(report["sold_variations"]["ignored_live_variations"], [])
        self.assertEqual(
            [variation["id"] for variation in report["sold_variations"]["unmapped_live_variations"]],
            ["UNMAPPED-LIVE-SOLD"],
        )
        self.assertEqual(report["summary"]["warning_count"], 1)

    def test_report_allows_warnings_without_blockers(self):
        merchant_context = MerchantContext(
            environment="production",
            merchant_id="merchant-1",
            status="active",
            auth_mode="oauth",
            location_id="LOC-1",
            writes_enabled=True,
            binding_version=3,
            display_name="Tea Shop",
        )
        binding = {
            "location_id": "LOC-1",
            "version": 3,
            "status": "draft",
            "mapping": {
                "sold_variation_aliases": {"LIVE-SOLD-1": "CANONICAL-SOLD-1"},
                "modifier_aliases": {"LIVE-MOD-1": "CANONICAL-MOD-1"},
                "inventory_variation_ids": {
                    "tea": "LIVE-INV-TEA",
                    "cup": "LIVE-INV-CUP",
                },
            },
        }
        client = _FakeClient(
            [
                _item(
                    "Tea",
                    _variation("LIVE-SOLD-1", item_name="Tea", variation_name="Regular"),
                    _variation("LIVE-INV-TEA", item_name="Tea Inventory", variation_name="Bag"),
                    _variation("LIVE-INV-CUP", item_name="Cup Inventory", variation_name="Box"),
                    _variation("LIVE-SOLD-2", item_name="Tea", variation_name="Large"),
                    _variation("CANONICAL-SOLD-2", item_name="Tea", variation_name="XL"),
                )
            ],
            [
                _modifier("LIVE-MOD-1", name="Boba"),
                _modifier("LIVE-MOD-2", name="Jelly"),
                _modifier("CANONICAL-MOD-2", name="Matcha Jelly"),
            ],
        )

        with (
            patch("app.binding_coverage_report.get_merchant_context", return_value=merchant_context),
            patch("app.binding_coverage_report.list_catalog_bindings", return_value=[binding]),
            patch("app.binding_coverage_report.get_active_catalog_binding", return_value=binding),
            patch(
                "app.binding_coverage_report.get_canonical_binding_targets",
                return_value={
                    "sold_variation_ids": {"CANONICAL-SOLD-1", "CANONICAL-SOLD-2"},
                    "modifier_ids": {"CANONICAL-MOD-1", "CANONICAL-MOD-2"},
                    "inventory_keys": {"tea", "cup"},
                },
            ),
            patch(
                "app.binding_coverage_report.create_square_client_for_merchant",
                return_value=client,
            ),
        ):
            report = build_binding_coverage_report("production", "merchant-1", "LOC-1")

        self.assertTrue(report["summary"]["ready_for_approval"])
        self.assertEqual(report["summary"]["blocking_issue_count"], 0)
        self.assertEqual(report["summary"]["warning_count"], 2)
        self.assertEqual(len(report["sold_variations"]["identity_covered_live_variations"]), 1)
        self.assertEqual(len(report["sold_variations"]["unmapped_live_variations"]), 1)
        self.assertEqual(len(report["modifiers"]["identity_covered_live_modifiers"]), 1)
        self.assertEqual(len(report["modifiers"]["unmapped_live_modifiers"]), 1)

    def test_report_flags_stale_and_missing_binding_coverage(self):
        merchant_context = MerchantContext(
            environment="production",
            merchant_id="merchant-1",
            status="active",
            auth_mode="oauth",
            location_id="LOC-1",
            writes_enabled=False,
            binding_version=4,
            display_name="Tea Shop",
        )
        binding = {
            "location_id": "LOC-1",
            "version": 4,
            "status": "draft",
            "mapping": {
                "sold_variation_aliases": {"MISSING-LIVE-SOLD": "UNKNOWN-CANONICAL-SOLD"},
                "modifier_aliases": {"MISSING-LIVE-MOD": "UNKNOWN-CANONICAL-MOD"},
                "inventory_variation_ids": {"tea": "MISSING-LIVE-INV"},
            },
        }
        client = _FakeClient([], [])

        with (
            patch("app.binding_coverage_report.get_merchant_context", return_value=merchant_context),
            patch("app.binding_coverage_report.list_catalog_bindings", return_value=[binding]),
            patch("app.binding_coverage_report.get_active_catalog_binding", return_value=None),
            patch(
                "app.binding_coverage_report.get_canonical_binding_targets",
                return_value={
                    "sold_variation_ids": {"CANONICAL-SOLD-1"},
                    "modifier_ids": {"CANONICAL-MOD-1"},
                    "inventory_keys": {"tea", "cup"},
                },
            ),
            patch(
                "app.binding_coverage_report.create_square_client_for_merchant",
                return_value=client,
            ),
        ):
            report = build_binding_coverage_report("production", "merchant-1", "LOC-1")

        self.assertFalse(report["summary"]["ready_for_approval"])
        self.assertEqual(report["summary"]["blocking_issue_count"], 6)
        self.assertEqual(
            report["inventory"]["missing_required_keys"],
            ["cup"],
        )
        self.assertEqual(
            report["sold_variations"]["unknown_canonical_targets"][0]["live_id"],
            "MISSING-LIVE-SOLD",
        )
        self.assertEqual(
            report["modifiers"]["stale_binding_sources"][0]["live_id"],
            "MISSING-LIVE-MOD",
        )


if __name__ == "__main__":
    unittest.main()
