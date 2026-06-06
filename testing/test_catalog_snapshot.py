import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.catalog_snapshot import (
    _build_client_id_map,
    _make_client_id,
    _rewrite_ids,
    _slugify,
    _strip_nested_duplicates,
    _strip_out_of_scope_refs,
    _strip_server_fields,
    export_snapshot,
    replay_snapshot,
)


def _make_obj(obj_id, model_dump_payload):
    """Build a fake SDK catalog object with model_dump() returning the given payload."""
    obj = MagicMock()
    obj.id = obj_id
    obj.model_dump.return_value = model_dump_payload
    return obj


class SlugifyTests(unittest.TestCase):
    def test_alnum_passthrough(self):
        self.assertEqual(_slugify("Latte"), "latte")

    def test_spaces_become_underscores(self):
        self.assertEqual(_slugify("Iced Vanilla Latte"), "iced_vanilla_latte")

    def test_strips_leading_trailing_underscores(self):
        self.assertEqual(_slugify("  16oz cup  "), "16oz_cup")

    def test_punctuation_collapses_and_strips_trailing_underscores(self):
        # _slugify replaces non-alnum chars with _ and then strips leading +
        # trailing underscores. So "Tea (Earl Grey)" — which ends with `)`
        # that becomes `_` — gets that trailing underscore stripped.
        self.assertEqual(_slugify("Tea (Earl Grey)"), "tea__earl_grey")


class MakeClientIdTests(unittest.TestCase):
    def test_uses_item_name(self):
        obj = {"id": "ABC", "type": "ITEM", "item_data": {"name": "Latte"}}
        self.assertEqual(_make_client_id(obj, set()), "#item_latte")

    def test_uses_modifier_list_name(self):
        obj = {
            "id": "ABC",
            "type": "MODIFIER_LIST",
            "modifier_list_data": {"name": "Size"},
        }
        self.assertEqual(_make_client_id(obj, set()), "#modifier_list_size")

    def test_falls_back_to_real_id_when_no_name(self):
        obj = {"id": "ABC123", "type": "ITEM", "item_data": {}}
        self.assertEqual(_make_client_id(obj, set()), "#item_abc123")

    def test_tie_break_on_duplicate_slug(self):
        obj1 = {"id": "AAAAAA", "type": "ITEM", "item_data": {"name": "Latte"}}
        used = {"#item_latte"}
        self.assertEqual(_make_client_id(obj1, used), "#item_latte_aaaaaa")


class StripOutOfScopeRefsTests(unittest.TestCase):
    def test_strips_image_ids_from_item(self):
        obj = {
            "type": "ITEM",
            "item_data": {
                "name": "Latte",
                "image_ids": ["IMG_ABC"],
                "variations": [],
            },
        }
        cleaned = _strip_out_of_scope_refs(obj)
        self.assertNotIn("image_ids", cleaned["item_data"])
        self.assertEqual(cleaned["item_data"]["name"], "Latte")

    def test_strips_tax_ids_from_item(self):
        obj = {"type": "ITEM", "item_data": {"tax_ids": ["TAX_ABC"], "name": "X"}}
        self.assertNotIn("tax_ids", _strip_out_of_scope_refs(obj)["item_data"])

    def test_preserves_unrelated_fields(self):
        obj = {"type": "ITEM", "item_data": {"name": "X", "description": "Y"}}
        self.assertEqual(_strip_out_of_scope_refs(obj), obj)

    def test_walks_nested_structures(self):
        obj = {
            "type": "ITEM",
            "item_data": {
                "variations": [
                    {
                        "type": "ITEM_VARIATION",
                        "item_variation_data": {"image_ids": ["IMG_X"]},
                    }
                ]
            },
        }
        cleaned = _strip_out_of_scope_refs(obj)
        var = cleaned["item_data"]["variations"][0]
        self.assertNotIn("image_ids", var["item_variation_data"])


class RewriteIdsTests(unittest.TestCase):
    def test_rewrites_top_level_id(self):
        id_map = {"ABC": "#item_latte"}
        self.assertEqual(_rewrite_ids("ABC", id_map), "#item_latte")

    def test_rewrites_nested_references(self):
        id_map = {"CAT_DRINKS": "#category_drinks", "MOD_SIZE": "#modifier_list_size"}
        obj = {
            "id": "ITEM_X",
            "item_data": {
                "category_id": "CAT_DRINKS",
                "modifier_list_info": [{"modifier_list_id": "MOD_SIZE"}],
            },
        }
        rewritten = _rewrite_ids(obj, id_map)
        self.assertEqual(rewritten["item_data"]["category_id"], "#category_drinks")
        self.assertEqual(
            rewritten["item_data"]["modifier_list_info"][0]["modifier_list_id"],
            "#modifier_list_size",
        )

    def test_leaves_unknown_strings_alone(self):
        id_map = {"ABC": "#x"}
        obj = {"name": "Latte", "description": "Not an ID"}
        self.assertEqual(_rewrite_ids(obj, id_map), obj)


class StripServerFieldsTests(unittest.TestCase):
    def test_strips_updated_at_and_version(self):
        obj = {
            "id": "#item_x",
            "type": "ITEM",
            "updated_at": "2026-01-01T00:00:00Z",
            "version": 42,
            "is_deleted": False,
            "item_data": {"name": "X"},
        }
        cleaned = _strip_server_fields(obj)
        self.assertNotIn("updated_at", cleaned)
        self.assertNotIn("version", cleaned)
        self.assertNotIn("is_deleted", cleaned)
        self.assertEqual(cleaned["id"], "#item_x")

    def test_strips_present_at_location_fields(self):
        obj = {
            "type": "ITEM",
            "present_at_all_locations": True,
            "present_at_location_ids": ["L1"],
            "absent_at_location_ids": [],
            "item_data": {"name": "X"},
        }
        cleaned = _strip_server_fields(obj)
        self.assertNotIn("present_at_all_locations", cleaned)
        self.assertNotIn("present_at_location_ids", cleaned)
        self.assertNotIn("absent_at_location_ids", cleaned)

    def test_strips_nested_location_overrides_from_item_variations(self):
        # Per-merchant references: each ITEM_VARIATION can have a
        # location_overrides array of per-location price/inventory settings.
        # The location_ids inside reference the SOURCE merchant's locations,
        # which don't exist in the target. Square rejects the batch with
        # "Object contains unknown location id" if we leave them in.
        obj = {
            "type": "ITEM",
            "id": "#item_latte",
            "item_data": {
                "name": "Latte",
                "variations": [
                    {
                        "type": "ITEM_VARIATION",
                        "id": "#item_variation_default",
                        "item_variation_data": {
                            "name": "Default",
                            "price_money": {"amount": 500, "currency": "USD"},
                            "location_overrides": [
                                {
                                    "location_id": "LB1MECVA7EZ8Z",
                                    "track_inventory": True,
                                    "price_money": {"amount": 550, "currency": "USD"},
                                }
                            ],
                        },
                    }
                ],
            },
        }
        cleaned = _strip_server_fields(obj)
        var = cleaned["item_data"]["variations"][0]
        self.assertNotIn("location_overrides", var["item_variation_data"])
        # Default price + name preserved
        self.assertEqual(var["item_variation_data"]["name"], "Default")
        self.assertEqual(var["item_variation_data"]["price_money"]["amount"], 500)


class StripNestedDuplicatesTests(unittest.TestCase):
    def test_drops_modifiers_array_inside_modifier_list_data(self):
        # The exact bug: Square returns modifiers both as top-level objects
        # (from list(types="MODIFIER")) and nested inside MODIFIER_LIST. Sending
        # both forms in batch_upsert produces "duplicate ID #modifier_X".
        obj = {
            "type": "MODIFIER_LIST",
            "id": "#modifier_list_ice_level",
            "modifier_list_data": {
                "name": "Ice Level",
                "selection_type": "SINGLE",
                "modifiers": [
                    {
                        "type": "MODIFIER",
                        "id": "#modifier_no_ice",
                        "modifier_data": {
                            "name": "No Ice",
                            "modifier_list_id": "#modifier_list_ice_level",
                        },
                    }
                ],
            },
        }
        cleaned = _strip_nested_duplicates(obj)
        self.assertNotIn("modifiers", cleaned["modifier_list_data"])
        # Other fields on modifier_list_data are preserved
        self.assertEqual(cleaned["modifier_list_data"]["name"], "Ice Level")
        self.assertEqual(cleaned["modifier_list_data"]["selection_type"], "SINGLE")

    def test_leaves_top_level_modifier_untouched(self):
        obj = {
            "type": "MODIFIER",
            "id": "#modifier_no_ice",
            "modifier_data": {
                "name": "No Ice",
                "modifier_list_id": "#modifier_list_ice_level",
            },
        }
        cleaned = _strip_nested_duplicates(obj)
        self.assertEqual(cleaned, obj)

    def test_leaves_item_with_nested_variations_untouched(self):
        # ITEM_VARIATION nested under item_data.variations stays — we don't
        # list ITEM_VARIATION at top level, so there's no duplicate.
        obj = {
            "type": "ITEM",
            "id": "#item_latte",
            "item_data": {
                "name": "Latte",
                "variations": [
                    {
                        "type": "ITEM_VARIATION",
                        "id": "#item_variation_default",
                        "item_variation_data": {"name": "Default"},
                    }
                ],
            },
        }
        cleaned = _strip_nested_duplicates(obj)
        self.assertEqual(cleaned, obj)

    def test_handles_modifier_list_without_nested_modifiers_array(self):
        # Defensive: if a MODIFIER_LIST has no modifiers array (e.g., empty
        # list, or omitted), nothing breaks.
        obj_no_modifiers = {
            "type": "MODIFIER_LIST",
            "id": "#ml_empty",
            "modifier_list_data": {"name": "Empty"},
        }
        self.assertEqual(_strip_nested_duplicates(obj_no_modifiers), obj_no_modifiers)


class BuildClientIdMapTests(unittest.TestCase):
    def test_returns_map_of_real_to_client_ids(self):
        objects = [
            {"id": "CAT1", "type": "CATEGORY", "category_data": {"name": "Drinks"}},
            {"id": "ITM1", "type": "ITEM", "item_data": {"name": "Latte"}},
        ]
        id_map = _build_client_id_map(objects)
        self.assertEqual(id_map["CAT1"], "#category_drinks")
        self.assertEqual(id_map["ITM1"], "#item_latte")

    def test_captures_nested_item_variation_ids(self):
        # Regression: in v1 we only collected top-level ids, so ITEM_VARIATION
        # ids nested inside item_data.variations leaked through as raw Square
        # IDs in the exported snapshot.
        objects = [
            {
                "id": "ITM_LATTE",
                "type": "ITEM",
                "item_data": {
                    "name": "Latte",
                    "variations": [
                        {
                            "id": "VAR_LATTE_DEFAULT",
                            "type": "ITEM_VARIATION",
                            "item_variation_data": {
                                "name": "Default",
                                "item_id": "ITM_LATTE",
                            },
                        }
                    ],
                },
            }
        ]
        id_map = _build_client_id_map(objects)
        self.assertEqual(id_map["ITM_LATTE"], "#item_latte")
        self.assertEqual(id_map["VAR_LATTE_DEFAULT"], "#item_variation_default")

    def test_captures_nested_modifiers_in_modifier_lists(self):
        # Modifiers can appear both top-level (via list(types=MODIFIER)) and
        # nested inside MODIFIER_LIST.modifier_list_data.modifiers. The walker
        # must collect both; dedup keeps it from double-counting.
        objects = [
            {
                "id": "ML_SIZE",
                "type": "MODIFIER_LIST",
                "modifier_list_data": {
                    "name": "Size",
                    "modifiers": [
                        {
                            "id": "MOD_SMALL",
                            "type": "MODIFIER",
                            "modifier_data": {
                                "name": "Small",
                                "modifier_list_id": "ML_SIZE",
                            },
                        }
                    ],
                },
            },
            {
                "id": "MOD_SMALL",
                "type": "MODIFIER",
                "modifier_data": {"name": "Small", "modifier_list_id": "ML_SIZE"},
            },
        ]
        id_map = _build_client_id_map(objects)
        self.assertEqual(id_map["ML_SIZE"], "#modifier_list_size")
        self.assertEqual(id_map["MOD_SMALL"], "#modifier_small")
        # No duplicate entries
        self.assertEqual(len(id_map), 2)

    def test_unique_client_ids_when_two_variations_share_a_name(self):
        # Many sandbox items have a single variation literally named "" (empty)
        # or "Default". The collision tie-break should produce unique client ids.
        objects = [
            {
                "id": "ITM_A",
                "type": "ITEM",
                "item_data": {
                    "name": "Latte",
                    "variations": [
                        {
                            "id": "VAR_A",
                            "type": "ITEM_VARIATION",
                            "item_variation_data": {"name": "Default"},
                        }
                    ],
                },
            },
            {
                "id": "ITM_B",
                "type": "ITEM",
                "item_data": {
                    "name": "Matcha",
                    "variations": [
                        {
                            "id": "VAR_B",
                            "type": "ITEM_VARIATION",
                            "item_variation_data": {"name": "Default"},
                        }
                    ],
                },
            },
        ]
        id_map = _build_client_id_map(objects)
        self.assertNotEqual(id_map["VAR_A"], id_map["VAR_B"])
        self.assertTrue(id_map["VAR_A"].startswith("#item_variation_default"))
        self.assertTrue(id_map["VAR_B"].startswith("#item_variation_default"))


class ExportSnapshotIntegrationTests(unittest.TestCase):
    def test_export_writes_file_with_rewritten_ids(self):
        category = _make_obj(
            "CAT_DRINKS",
            {"id": "CAT_DRINKS", "type": "CATEGORY", "category_data": {"name": "Drinks"}},
        )
        item = _make_obj(
            "ITM_LATTE",
            {
                "id": "ITM_LATTE",
                "type": "ITEM",
                "updated_at": "2026-01-01T00:00:00Z",
                "version": 1,
                "item_data": {
                    "name": "Latte",
                    "category_id": "CAT_DRINKS",
                    "image_ids": ["IMG_SHOULD_BE_STRIPPED"],
                    "tax_ids": ["TAX_SHOULD_BE_STRIPPED"],
                    "variations": [],
                },
            },
        )

        client = MagicMock()
        client.catalog.list = MagicMock(
            side_effect=lambda types: {
                "CATEGORY": [category],
                "MEASUREMENT_UNIT": [],
                "MODIFIER_LIST": [],
                "MODIFIER": [],
                "ITEM": [item],
            }[types]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "scripts.catalog_snapshot.SNAPSHOT_DIR",
                Path(tmpdir),
            ):
                exit_code = export_snapshot(client, "test_account")

            self.assertEqual(exit_code, 0)
            out_file = Path(tmpdir) / "test_account.json"
            self.assertTrue(out_file.exists())
            snapshot = json.loads(out_file.read_text())

        self.assertEqual(snapshot["snapshot_meta"]["total_objects"], 2)
        self.assertEqual(
            snapshot["snapshot_meta"]["object_counts"],
            {"CATEGORY": 1, "ITEM": 1},
        )

        objects_by_type = {o["type"]: o for o in snapshot["objects"]}
        self.assertEqual(objects_by_type["CATEGORY"]["id"], "#category_drinks")
        self.assertEqual(objects_by_type["ITEM"]["id"], "#item_latte")
        self.assertEqual(
            objects_by_type["ITEM"]["item_data"]["category_id"],
            "#category_drinks",
        )
        # Out-of-scope refs stripped
        self.assertNotIn("image_ids", objects_by_type["ITEM"]["item_data"])
        self.assertNotIn("tax_ids", objects_by_type["ITEM"]["item_data"])

    def test_export_deduplicates_by_id(self):
        # Modifiers can be returned both via list(types=MODIFIER) and as
        # children of MODIFIER_LIST in some sdk versions. The dedup logic
        # must keep us from double-exporting them.
        mod1 = _make_obj(
            "MOD_X",
            {"id": "MOD_X", "type": "MODIFIER", "modifier_data": {"name": "Foo"}},
        )

        client = MagicMock()
        client.catalog.list = MagicMock(
            side_effect=lambda types: {
                "CATEGORY": [],
                "MEASUREMENT_UNIT": [],
                "MODIFIER_LIST": [],
                "MODIFIER": [mod1, mod1],  # duplicate input
                "ITEM": [],
            }[types]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "scripts.catalog_snapshot.SNAPSHOT_DIR",
                Path(tmpdir),
            ):
                export_snapshot(client, "dedup_test")

            snapshot = json.loads(
                (Path(tmpdir) / "dedup_test.json").read_text()
            )
        self.assertEqual(len(snapshot["objects"]), 1)


class ReplaySnapshotIntegrationTests(unittest.TestCase):
    def _write_snapshot(self, tmpdir, objects):
        path = Path(tmpdir) / "test.json"
        path.write_text(
            json.dumps(
                {
                    "snapshot_meta": {
                        "account_slug": "test",
                        "exported_at": "2026-01-01T00:00:00Z",
                        "object_counts": {"ITEM": len(objects)},
                        "total_objects": len(objects),
                    },
                    "objects": objects,
                }
            )
        )
        return path

    def test_replay_dry_run_does_not_call_batch_upsert(self):
        objects = [
            {"id": "#item_x", "type": "ITEM", "item_data": {"name": "X"}}
        ]
        client = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_snapshot(tmpdir, objects)
            with patch(
                "scripts.catalog_snapshot.SNAPSHOT_DIR",
                Path(tmpdir),
            ):
                exit_code = replay_snapshot(client, "test", apply=False)
        self.assertEqual(exit_code, 0)
        client.catalog.batch_upsert.assert_not_called()

    def test_replay_apply_calls_batch_upsert_with_cleaned_objects(self):
        objects = [
            {
                "id": "#item_x",
                "type": "ITEM",
                "updated_at": "2026-01-01T00:00:00Z",
                "version": 5,
                "item_data": {"name": "X"},
            }
        ]
        client = MagicMock()
        client.catalog.batch_upsert.return_value = SimpleNamespace(
            objects=[SimpleNamespace(id="real_id_1")],
            id_mappings=[SimpleNamespace(client_object_id="#item_x", object_id="real_id_1")],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_snapshot(tmpdir, objects)
            with patch(
                "scripts.catalog_snapshot.SNAPSHOT_DIR",
                Path(tmpdir),
            ):
                exit_code = replay_snapshot(client, "test", apply=True)

        self.assertEqual(exit_code, 0)
        client.catalog.batch_upsert.assert_called_once()
        call = client.catalog.batch_upsert.call_args
        # Confirm server-assigned fields were stripped before send.
        sent_objects = call.kwargs["batches"][0]["objects"]
        self.assertEqual(len(sent_objects), 1)
        self.assertNotIn("updated_at", sent_objects[0])
        self.assertNotIn("version", sent_objects[0])
        self.assertEqual(sent_objects[0]["item_data"]["name"], "X")

    def test_replay_with_missing_file_returns_error(self):
        client = MagicMock()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "scripts.catalog_snapshot.SNAPSHOT_DIR",
                Path(tmpdir),
            ):
                exit_code = replay_snapshot(client, "nonexistent", apply=True)
        self.assertEqual(exit_code, 1)
        client.catalog.batch_upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
