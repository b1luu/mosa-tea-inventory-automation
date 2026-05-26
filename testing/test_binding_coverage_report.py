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


def _archived_variation(variation_id, *, item_id, variation_name, sellable=True, stockable=True):
    return type(
        "ArchivedVariation",
        (),
        {
            "id": variation_id,
            "type": "ITEM_VARIATION",
            "item_variation_data": type(
                "VariationData",
                (),
                {
                    "name": variation_name,
                    "item_id": item_id,
                    "sellable": sellable,
                    "stockable": stockable,
                },
            )(),
        },
    )()


def _related_item(item_id, name):
    return type(
        "RelatedItem",
        (),
        {"id": item_id, "type": "ITEM", "item_data": type("ItemData", (), {"name": name})()},
    )()


class _FakeCatalog:
    def __init__(self, items, modifiers, by_id=None, related=None):
        self._items = items
        self._modifiers = modifiers
        self._by_id = {obj.id: obj for obj in (by_id or [])}
        self._related = list(related or [])

    def list(self, *, types):
        if types == "ITEM":
            return list(self._items)
        if types == "MODIFIER":
            return list(self._modifiers)
        raise AssertionError(types)

    def batch_get(self, *, object_ids, include_related_objects=False):
        objects = [self._by_id[i] for i in object_ids if i in self._by_id]
        return type("BatchGetResponse", (), {"objects": objects, "related_objects": self._related})()


class _FakeClient:
    def __init__(self, items, modifiers, by_id=None, related=None):
        self.catalog = _FakeCatalog(items, modifiers, by_id=by_id, related=related)


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


class ArchivedBackfillTests(unittest.TestCase):
    """#2: archived inventory items are gone from `catalog.list` but must be
    fetched by ID so the coverage report doesn't false-flag them as stale."""

    def _run(self, client):
        with (
            patch("app.binding_coverage_report.get_merchant_context", return_value=None),
            patch("app.binding_coverage_report.list_catalog_bindings", return_value=[self.binding]),
            patch("app.binding_coverage_report.get_active_catalog_binding", return_value=self.binding),
            patch(
                "app.binding_coverage_report.get_canonical_binding_targets",
                return_value={
                    "sold_variation_ids": set(),
                    "modifier_ids": set(),
                    "inventory_keys": {"tgy"},
                },
            ),
            patch(
                "app.binding_coverage_report.create_square_client_for_merchant",
                return_value=client,
            ),
        ):
            return build_binding_coverage_report("production", "merchant-1", "LOC-1")

    def setUp(self):
        self.binding = {
            "location_id": "LOC-1",
            "version": 1,
            "status": "draft",
            "mapping": {
                "sold_variation_aliases": {},
                "modifier_aliases": {},
                "inventory_variation_ids": {"tgy": "ARCHIVED-INV-1"},
                "ignored_live_variation_ids": [],
            },
        }

    def test_archived_inventory_item_fetched_by_id_is_not_stale(self):
        # ARCHIVED-INV-1 is absent from list() (archived) but available by ID.
        client = _FakeClient(
            [],
            [],
            by_id=[_archived_variation("ARCHIVED-INV-1", item_id="ITEM-1", variation_name="600 g bags")],
            related=[_related_item("ITEM-1", "TGY")],
        )
        report = self._run(client)

        self.assertEqual(report["inventory"]["stale_live_variation_ids"], [])
        self.assertEqual(report["inventory"]["missing_required_keys"], [])
        self.assertEqual(report["summary"]["blocking_issue_count"], 0)
        self.assertTrue(report["summary"]["ready_for_approval"])

    def test_genuinely_missing_inventory_id_is_still_flagged_stale(self):
        # Not in list() and not retrievable by ID -> must still be flagged.
        client = _FakeClient([], [], by_id=[], related=[])
        report = self._run(client)

        self.assertEqual(
            [entry["live_variation_id"] for entry in report["inventory"]["stale_live_variation_ids"]],
            ["ARCHIVED-INV-1"],
        )
        self.assertGreaterEqual(report["summary"]["blocking_issue_count"], 1)
        self.assertFalse(report["summary"]["ready_for_approval"])


if __name__ == "__main__":
    unittest.main()
