import unittest

from app.catalog_binding_resolver import (
    canonicalize_order_summary,
    resolve_inventory_variation_id,
)


class CatalogBindingResolverTests(unittest.TestCase):
    def test_canonicalize_order_summary_maps_live_ids_to_canonical_ids(self):
        realistic_location_id = "LB1MECVA7EZ8Z"
        order_summary = {
            "id": "order-1",
            "location_id": realistic_location_id,
            "line_items": [
                {
                    "catalog_object_id": "LIVE-SOLD-1",
                    "modifiers": [
                        {"catalog_object_id": "LIVE-MOD-1"},
                        {"catalog_object_id": "UNCHANGED-MOD"},
                    ],
                }
            ],
        }
        binding = {
            "mapping": {
                "sold_variation_aliases": {
                    "LIVE-SOLD-1": "CANONICAL-SOLD-1",
                },
                "modifier_aliases": {
                    "LIVE-MOD-1": "CANONICAL-MOD-1",
                },
            }
        }

        canonicalized = canonicalize_order_summary(order_summary, binding)

        self.assertEqual(
            canonicalized["line_items"][0]["catalog_object_id"],
            "CANONICAL-SOLD-1",
        )
        self.assertEqual(
            canonicalized["line_items"][0]["modifiers"][0]["catalog_object_id"],
            "CANONICAL-MOD-1",
        )
        self.assertEqual(
            canonicalized["line_items"][0]["modifiers"][1]["catalog_object_id"],
            "UNCHANGED-MOD",
        )
        self.assertEqual(
            order_summary["line_items"][0]["catalog_object_id"],
            "LIVE-SOLD-1",
        )
        self.assertEqual(canonicalized["location_id"], realistic_location_id)

    def test_canonicalize_drops_ignored_line_items_keeps_others(self):
        # Mixed order: one mapped item, one ignored item, one unknown item.
        # Ignored item should be dropped (no block). Unknown item stays so
        # downstream projection fails and blocks the order (safety net for
        # forgotten recipe additions).
        order_summary = {
            "id": "order-1",
            "location_id": "LB1MECVA7EZ8Z",
            "line_items": [
                {"catalog_object_id": "LIVE-SOLD-1", "name": "Mapped Drink"},
                {"catalog_object_id": "LIVE-IGNORED", "name": "SSR Special"},
                {"catalog_object_id": "LIVE-UNKNOWN", "name": "New Drink"},
            ],
        }
        binding = {
            "mapping": {
                "sold_variation_aliases": {"LIVE-SOLD-1": "CANONICAL-SOLD-1"},
                "modifier_aliases": {},
                "ignored_live_variation_ids": ["LIVE-IGNORED"],
            }
        }

        canonicalized = canonicalize_order_summary(order_summary, binding)

        ids = [li["catalog_object_id"] for li in canonicalized["line_items"]]
        self.assertEqual(ids, ["CANONICAL-SOLD-1", "LIVE-UNKNOWN"])
        # Input order untouched
        self.assertEqual(len(order_summary["line_items"]), 3)

    def test_canonicalize_no_ignored_list_still_works(self):
        order_summary = {
            "line_items": [{"catalog_object_id": "LIVE-1"}]
        }
        binding = {"mapping": {"sold_variation_aliases": {"LIVE-1": "C-1"}}}
        canonicalized = canonicalize_order_summary(order_summary, binding)
        self.assertEqual(canonicalized["line_items"][0]["catalog_object_id"], "C-1")

    def test_resolve_inventory_variation_id_returns_bound_id(self):
        binding = {
            "mapping": {
                "inventory_variation_ids": {
                    "tgy": "LIVE-INV-TGY",
                }
            }
        }

        self.assertEqual(
            resolve_inventory_variation_id("tgy", binding),
            "LIVE-INV-TGY",
        )

    def test_resolve_inventory_variation_id_raises_when_missing(self):
        with self.assertRaises(KeyError):
            resolve_inventory_variation_id("tgy", {"mapping": {}})


if __name__ == "__main__":
    unittest.main()
