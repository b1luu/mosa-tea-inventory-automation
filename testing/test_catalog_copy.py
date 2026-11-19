"""1:1 catalog copy: archived backfill, replay guard, ID map, binding
translation, verify and counts. Fakes only; every fake raises if called in a
way the test did not expect, so a missing guard fails instead of hanging."""

import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import catalog_snapshot as cs

PROD_MERCHANT = "PRODMERCHANT1"
PROD_LOCATION = "PRODLOCATION1"
SANDBOX_MERCHANT = "SANDBOXMERCHANT1"
SANDBOX_LOCATION = "SANDBOXLOCATION1"


class Unexpected(AssertionError):
    pass


class FakeObj:
    def __init__(self, payload):
        self._payload = payload
        self.id = payload["id"]

    def model_dump(self, mode=None, exclude_none=None):
        return copy.deepcopy(self._payload)


class StrictNamespace:
    """Attribute access for anything not set raises, so unexpected API calls fail."""

    def __init__(self, name, **methods):
        self._name = name
        for key, value in methods.items():
            setattr(self, key, value)

    def __getattr__(self, attr):
        raise Unexpected(f"unexpected call: {self._name}.{attr}")


class FakeSquare:
    """Listed objects (what catalog.list returns) and hidden ones (archived:
    only batch_get returns them)."""

    def __init__(self, listed=(), hidden=(), *, upsert_response=None, counts=None):
        self.listed = [copy.deepcopy(p) for p in listed]
        self.by_id = {}
        for payload in list(self.listed) + [copy.deepcopy(p) for p in hidden]:
            self._index(payload)
        self.upsert_calls = []
        self.batch_get_calls = []
        self.change_calls = []
        self._upsert_response = upsert_response
        self._counts = counts or {}
        self.catalog = StrictNamespace(
            "catalog", list=self._list, batch_get=self._batch_get, batch_upsert=self._batch_upsert
        )
        self.inventory = StrictNamespace(
            "inventory", batch_get_counts=self._batch_get_counts, batch_create_changes=self._changes
        )

    def _index(self, payload):
        self.by_id[payload["id"]] = payload
        for variation in (payload.get("item_data") or {}).get("variations") or []:
            self.by_id[variation["id"]] = variation

    def _list(self, *, types):
        return [FakeObj(p) for p in self.listed if p["type"] == types]

    def _batch_get(self, *, object_ids, include_related_objects):
        self.batch_get_calls.append(list(object_ids))
        objects, related = [], []
        for object_id in object_ids:
            payload = self.by_id.get(object_id)
            if payload is None:
                continue
            objects.append(FakeObj(payload))
            parent_id = (payload.get("item_variation_data") or {}).get("item_id")
            if include_related_objects and parent_id in self.by_id:
                related.append(FakeObj(self.by_id[parent_id]))
        return SimpleNamespace(objects=objects, related_objects=related)

    def _batch_upsert(self, *, idempotency_key, batches):
        self.upsert_calls.append(batches)
        if self._upsert_response is None:
            raise Unexpected("batch_upsert was not expected in this test")
        return self._upsert_response(batches)

    def _batch_get_counts(self, *, catalog_object_ids, location_ids, states):
        return [
            SimpleNamespace(catalog_object_id=i, quantity=self._counts[i])
            for i in catalog_object_ids
            if i in self._counts
        ]

    def _changes(self, *, idempotency_key, changes):
        self.change_calls.append(changes)
        return SimpleNamespace(counts=[])


def _assign_real_ids(batches):
    """Fake Square: every #client_id in the batch gets a real sandbox ID."""
    ids = set()
    for batch in batches:
        for obj in batch["objects"]:
            ids |= cs._collect_all_ids(obj)
    mappings = [
        SimpleNamespace(client_object_id=c, object_id=f"SBOBJECT{index:016d}")
        for index, c in enumerate(sorted(ids))
    ]
    return SimpleNamespace(objects=[SimpleNamespace(id=m.object_id) for m in mappings], id_mappings=mappings)


# ------------------------------------------------------------ prod fixtures


def _item(item_id, name, var_id, var_name="Regular", *, archived=False, category_id="CATDRINKS0000000000000000"):
    data = {
        "name": name,
        "category_id": category_id,
        "variations": [
            {
                "id": var_id,
                "type": "ITEM_VARIATION",
                "version": 7,
                "item_variation_data": {"item_id": item_id, "name": var_name},
            }
        ],
    }
    if archived:
        data["is_archived"] = True
    return {"id": item_id, "type": "ITEM", "version": 3, "updated_at": "2026-11-01T00:00:00Z", "item_data": data}


CATEGORY = {"id": "CATDRINKS0000000000000000", "type": "CATEGORY", "category_data": {"name": "Drinks"}}
MOD_LIST = {
    "id": "MODLISTTOPPINGS000000000",
    "type": "MODIFIER_LIST",
    "modifier_list_data": {"name": "Toppings"},
}
BOBA = {
    "id": "MODBOBA00000000000000000",
    "type": "MODIFIER",
    "modifier_data": {"name": "Boba", "modifier_list_id": "MODLISTTOPPINGS000000000"},
}
MILK_TEA = _item("ITEMMILKTEA0000000000000", "Milk Tea", "VARMILKTEA00000000000000")
# Archived backend inventory item: catalog.list omits it.
TGY_LEAF = _item(
    "ITEMTGYLEAF0000000000000", "TGY Leaf (bag)", "VARTGYLEAF00000000000000", archived=True
)

PROD_MAPPING = {
    "sold_variation_aliases": {"VARMILKTEA00000000000000": "milk_tea_regular"},
    "modifier_aliases": {"MODBOBA00000000000000000": "boba"},
    "inventory_variation_ids": {"tgy": "VARTGYLEAF00000000000000"},
    "ignored_live_variation_ids": [],
    "ignored_live_modifier_ids": [],
}
SOURCE = {
    "environment": "production",
    "merchant_id": PROD_MERCHANT,
    "location_id": PROD_LOCATION,
    "binding_version": 7,
    "mapping": PROD_MAPPING,
}


def _prod_square():
    return FakeSquare(listed=[CATEGORY, MOD_LIST, BOBA, MILK_TEA], hidden=[TGY_LEAF])


@contextmanager
def _snapshot_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(cs, "SNAPSHOT_DIR", Path(tmpdir)), patch("builtins.print"):
            yield Path(tmpdir)


@contextmanager
def _sandbox_settings():
    with patch.dict(
        "os.environ",
        {
            "DYNAMODB_MERCHANT_CONNECTION_TABLE": "mosa-tea-merchant-connections",
            "DYNAMODB_MERCHANT_CATALOG_BINDING_TABLE": "mosa-tea-merchant-bindings",
            "MERCHANT_SECRET_PREFIX": "mosa-tea/merchant-auth",
        },
    ):
        yield


def _export_and_replay(tmp):
    """Export prod, replay onto an empty sandbox. Returns the sandbox fake."""
    cs.export_snapshot(_prod_square(), "mosa_prod_test", source=SOURCE)
    sandbox = FakeSquare(upsert_response=_assign_real_ids)
    with _sandbox_settings():
        exit_code = cs.replay_snapshot(sandbox, "mosa_prod_test", True, environment="sandbox")
    assert exit_code == 0, exit_code
    return sandbox


def _strict(name):
    def _fail(*args, **kwargs):
        raise Unexpected(f"unexpected call: {name}")

    return _fail


class ArchivedBackfillTests(unittest.TestCase):
    def test_backfill_finds_an_archived_item_catalog_list_omitted(self):
        with _snapshot_dir() as tmp:
            exit_code = cs.export_snapshot(_prod_square(), "mosa_prod_test", source=SOURCE)
            snapshot = json.loads((tmp / "mosa_prod_test.json").read_text())

        self.assertEqual(exit_code, 0)
        by_client = {o["id"]: o for o in snapshot["objects"]}
        tgy_client = snapshot["source_ids"]["ITEMTGYLEAF0000000000000"]
        self.assertTrue(by_client[tgy_client]["item_data"]["is_archived"])
        self.assertIn("VARTGYLEAF00000000000000", snapshot["source_ids"])
        self.assertEqual(snapshot["snapshot_meta"]["archived_items"], 1)
        self.assertEqual(snapshot["snapshot_meta"]["object_counts"]["ITEM"], 2)
        # The variation arrives nested in its parent, not also top-level.
        self.assertNotIn("ITEM_VARIATION", snapshot["snapshot_meta"]["object_counts"])

    def test_backfill_adds_nested_modifiers_of_a_backfilled_list(self):
        hidden_list = {
            "id": "MODLISTSEASONAL000000000",
            "type": "MODIFIER_LIST",
            "modifier_list_data": {
                "name": "Seasonal",
                "modifiers": [
                    {
                        "id": "MODPUMPKIN00000000000000",
                        "type": "MODIFIER",
                        "modifier_data": {"name": "Pumpkin", "modifier_list_id": "MODLISTSEASONAL000000000"},
                    }
                ],
            },
        }
        square = FakeSquare(listed=[CATEGORY], hidden=[hidden_list])
        payloads = cs._list_catalog(square)
        added, missing = cs.backfill_by_id(square, payloads, {"MODLISTSEASONAL000000000"})

        self.assertEqual(missing, [])
        self.assertEqual(sorted(p["type"] for p in added), ["MODIFIER", "MODIFIER_LIST"])

    def test_export_reports_binding_ids_that_do_not_exist_anywhere(self):
        source = copy.deepcopy(SOURCE)
        source["mapping"]["inventory_variation_ids"]["ghost"] = "VARDELETED00000000000000"
        with _snapshot_dir():
            exit_code = cs.export_snapshot(_prod_square(), "mosa_prod_test", source=source)
        self.assertEqual(exit_code, 1)


class ReplayGuardTests(unittest.TestCase):
    def test_replay_refuses_a_non_empty_account(self):
        with _snapshot_dir():
            cs.export_snapshot(_prod_square(), "mosa_prod_test", source=SOURCE)
            target = FakeSquare(listed=[CATEGORY])  # batch_upsert raises if called
            with _sandbox_settings():
                exit_code = cs.replay_snapshot(target, "mosa_prod_test", True, environment="sandbox")
        self.assertEqual(exit_code, 1)
        self.assertEqual(target.upsert_calls, [])

    def test_force_allows_a_non_empty_account(self):
        with _snapshot_dir():
            cs.export_snapshot(_prod_square(), "mosa_prod_test", source=SOURCE)
            target = FakeSquare(listed=[CATEGORY], upsert_response=_assign_real_ids)
            with _sandbox_settings():
                exit_code = cs.replay_snapshot(
                    target, "mosa_prod_test", True, force=True, environment="sandbox"
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(target.upsert_calls), 1)

    def test_replay_never_writes_to_production(self):
        with _snapshot_dir():
            cs.export_snapshot(_prod_square(), "mosa_prod_test", source=SOURCE)
            target = FakeSquare()
            exit_code = cs.replay_snapshot(target, "mosa_prod_test", True, environment="production")
            with patch.dict("os.environ", {"DYNAMODB_MERCHANT_CATALOG_BINDING_TABLE": "mosa-tea-merchant-bindings-prod"}):
                prod_tables_exit = cs.replay_snapshot(target, "mosa_prod_test", True, environment="sandbox")
        self.assertEqual((exit_code, prod_tables_exit), (1, 1))
        self.assertEqual(target.upsert_calls, [])

    def test_production_reads_never_refresh_the_token(self):
        with (
            patch.object(cs, "resolve_merchant_access_token", return_value="token") as mock_resolve,
            patch.object(cs, "create_square_client", return_value="client"),
        ):
            cs.create_client("production", PROD_MERCHANT)
        self.assertFalse(mock_resolve.call_args.kwargs["refresh_if_needed"])


class IdMapTests(unittest.TestCase):
    def test_id_map_covers_every_prod_object_including_archived_and_nested(self):
        with _snapshot_dir() as tmp:
            _export_and_replay(tmp)
            idmap = json.loads((tmp / "mosa_prod_test.idmap.json").read_text())
            snapshot = json.loads((tmp / "mosa_prod_test.json").read_text())

        prod_to_sandbox = {e["prod_id"]: e["sandbox_id"] for e in idmap["objects"]}
        self.assertEqual(set(prod_to_sandbox), set(snapshot["source_ids"]))
        self.assertTrue(all(prod_to_sandbox.values()))
        for prod_id in ("VARTGYLEAF00000000000000", "VARMILKTEA00000000000000", "MODBOBA00000000000000000"):
            self.assertTrue(prod_to_sandbox[prod_id].startswith("SB"))

    def test_incomplete_upsert_response_is_an_error_and_still_writes_the_map(self):
        def _drop_one(batches):
            response = _assign_real_ids(batches)
            response.id_mappings = response.id_mappings[1:]
            return response

        with _snapshot_dir() as tmp:
            cs.export_snapshot(_prod_square(), "mosa_prod_test", source=SOURCE)
            target = FakeSquare(upsert_response=_drop_one)
            with _sandbox_settings():
                exit_code = cs.replay_snapshot(target, "mosa_prod_test", True, environment="sandbox")
            written = (tmp / "mosa_prod_test.idmap.json").exists()
        self.assertEqual(exit_code, 1)
        self.assertTrue(written)


class TranslateBindingTests(unittest.TestCase):
    def _translate(self, tmp, *, report_ready=True, mapping=None):
        if mapping is not None:
            path = tmp / "mosa_prod_test.json"
            snapshot = json.loads(path.read_text())
            snapshot["source"]["mapping"] = mapping
            path.write_text(json.dumps(snapshot))
        upserts = []
        with (
            _sandbox_settings(),
            patch.object(cs, "list_catalog_bindings", return_value=[]),
            patch.object(cs, "upsert_catalog_binding", side_effect=lambda *a, **k: upserts.append((a, k))),
            patch.object(
                cs,
                "build_coverage_report",
                return_value={"summary": {"ready_for_approval": report_ready, "blocking_issue_count": 0}},
            ),
            patch.object(cs, "get_merchant_context", side_effect=_strict("get_merchant_context")),
        ):
            result = cs.translate_binding("mosa_prod_test", "sandbox", SANDBOX_MERCHANT, SANDBOX_LOCATION)
        return result, upserts

    def test_translation_rewrites_every_id_field(self):
        with _snapshot_dir() as tmp:
            _export_and_replay(tmp)
            idmap = json.loads((tmp / "mosa_prod_test.idmap.json").read_text())
            (exit_code, version), upserts = self._translate(tmp)

        p2s = {e["prod_id"]: e["sandbox_id"] for e in idmap["objects"]}
        (args, _kwargs), = upserts
        environment, merchant, location, upsert_version, mapping = args
        self.assertEqual((exit_code, version, upsert_version), (0, 1, 1))
        self.assertEqual((environment, merchant, location), ("sandbox", SANDBOX_MERCHANT, SANDBOX_LOCATION))
        self.assertEqual(mapping["sold_variation_aliases"], {p2s["VARMILKTEA00000000000000"]: "milk_tea_regular"})
        self.assertEqual(mapping["modifier_aliases"], {p2s["MODBOBA00000000000000000"]: "boba"})
        self.assertEqual(mapping["inventory_variation_ids"], {"tgy": p2s["VARTGYLEAF00000000000000"]})
        self.assertFalse(cs._collect_id_like_strings(mapping) & set(p2s))

    def test_unmapped_prod_id_is_an_error_and_nothing_is_upserted(self):
        mapping = copy.deepcopy(PROD_MAPPING)
        mapping["ignored_live_variation_ids"] = ["VARNOTINMAP0000000000000"]
        with _snapshot_dir() as tmp:
            _export_and_replay(tmp)
            with self.assertRaisesRegex(ValueError, "VARNOTINMAP0000000000000"):
                self._translate(tmp, mapping=mapping)

    def test_not_ready_for_approval_exits_nonzero(self):
        with _snapshot_dir() as tmp:
            _export_and_replay(tmp)
            (exit_code, _), _ = self._translate(tmp, report_ready=False)
        self.assertEqual(exit_code, 1)

    def test_translation_refuses_production(self):
        with _snapshot_dir() as tmp:
            _export_and_replay(tmp)
            with (
                patch.object(cs, "upsert_catalog_binding", side_effect=_strict("upsert_catalog_binding")),
                self.assertRaises(ValueError),
            ):
                cs.translate_binding("mosa_prod_test", "production", SANDBOX_MERCHANT, SANDBOX_LOCATION)


class VerifyTests(unittest.TestCase):
    def _sandbox_catalog(self, tmp, mutate=None):
        """The sandbox after a faithful replay: what Square would list and hide."""
        sandbox = _export_and_replay(tmp)
        idmap = json.loads((tmp / "mosa_prod_test.idmap.json").read_text())
        client_to_sandbox = {e["client_id"]: e["sandbox_id"] for e in idmap["objects"]}
        (batch,) = sandbox.upsert_calls[0]
        created = [cs._rewrite_ids(copy.deepcopy(o), client_to_sandbox) for o in batch["objects"]]
        for obj in created:
            obj["version"] = 1
            obj["updated_at"] = "2026-11-19T12:00:00Z"
        if mutate:
            created = mutate(created)
        listed = [o for o in created if not cs._is_archived(o)]
        hidden = [o for o in created if cs._is_archived(o)]
        return FakeSquare(listed=listed, hidden=hidden)

    def _verify(self, mutate=None):
        with _snapshot_dir() as tmp:
            target = self._sandbox_catalog(tmp, mutate)
            report = cs.compare_catalogs(
                json.loads((tmp / "mosa_prod_test.json").read_text())["objects"],
                self._export_target(target, tmp),
                json.loads((tmp / "mosa_prod_test.idmap.json").read_text()),
            )
            exit_code = cs.verify(target, "mosa_prod_test")
        return exit_code, report

    @staticmethod
    def _export_target(target, tmp):
        idmap = json.loads((tmp / "mosa_prod_test.idmap.json").read_text())
        payloads = cs._list_catalog(target)
        cs.backfill_by_id(target, payloads, {e["sandbox_id"] for e in idmap["objects"]})
        return payloads

    @staticmethod
    def _named(name):
        return lambda o: cs._extract_name(o) == name

    def test_faithful_copy_has_zero_differences(self):
        exit_code, report = self._verify()
        self.assertEqual(report, {"missing": [], "extra": [], "different": []})
        self.assertEqual(exit_code, 0)

    def test_verify_catches_a_missing_item(self):
        exit_code, report = self._verify(lambda objs: [o for o in objs if not self._named("Milk Tea")(o)])
        self.assertEqual(report["missing"], ["ITEM 'Milk Tea'"])
        self.assertEqual(exit_code, 1)

    def test_verify_catches_an_extra_item(self):
        extra = _item("SBEXTRAITEM0000000000000", "Mystery Drink", "SBEXTRAVAR00000000000000")
        exit_code, report = self._verify(lambda objs: objs + [extra])
        self.assertEqual(report["extra"], ["ITEM 'Mystery Drink'"])
        self.assertEqual(exit_code, 1)

    def test_verify_catches_a_changed_field(self):
        def _rename(objs):
            for o in objs:
                if self._named("Boba")(o):
                    o["modifier_data"]["name"] = "Boba (old)"
            return objs

        exit_code, report = self._verify(_rename)
        (diff,) = report["different"]
        self.assertIn("modifier_data.name", diff["fields"])
        self.assertFalse(diff["is_archived_changed"])
        self.assertEqual(exit_code, 1)

    def test_verify_catches_a_changed_is_archived(self):
        def _unarchive(objs):
            for o in objs:
                if self._named("TGY Leaf (bag)")(o):
                    del o["item_data"]["is_archived"]
            return objs

        exit_code, report = self._verify(_unarchive)
        (diff,) = report["different"]
        self.assertTrue(diff["is_archived_changed"])
        self.assertEqual(exit_code, 1)


class CountsTests(unittest.TestCase):
    def _counts_ready(self, tmp):
        _export_and_replay(tmp)
        prod = FakeSquare(counts={"VARTGYLEAF00000000000000": "12.5"})
        cs.export_counts(prod, "mosa_prod_test")

    def test_copy_counts_dry_run_writes_nothing(self):
        with _snapshot_dir() as tmp:
            self._counts_ready(tmp)
            target = FakeSquare()
            exit_code = cs.copy_counts(target, "mosa_prod_test", "sandbox", SANDBOX_LOCATION, False)
        self.assertEqual(exit_code, 0)
        self.assertEqual(target.change_calls, [])

    def test_copy_counts_apply_writes_physical_counts_to_sandbox_ids(self):
        with _snapshot_dir() as tmp:
            self._counts_ready(tmp)
            idmap = json.loads((tmp / "mosa_prod_test.idmap.json").read_text())
            target = FakeSquare()
            with _sandbox_settings():
                cs.copy_counts(target, "mosa_prod_test", "sandbox", SANDBOX_LOCATION, True)

        p2s = {e["prod_id"]: e["sandbox_id"] for e in idmap["objects"]}
        ((change,),) = target.change_calls
        self.assertEqual(change["type"], "PHYSICAL_COUNT")
        self.assertEqual(change["physical_count"]["catalog_object_id"], p2s["VARTGYLEAF00000000000000"])
        self.assertEqual(change["physical_count"]["location_id"], SANDBOX_LOCATION)
        self.assertEqual(change["physical_count"]["quantity"], "12.5")

    def test_copy_counts_apply_refuses_production(self):
        with _snapshot_dir() as tmp:
            self._counts_ready(tmp)
            target = FakeSquare()
            with self.assertRaises(ValueError):
                cs.copy_counts(target, "mosa_prod_test", "production", SANDBOX_LOCATION, True)
        self.assertEqual(target.change_calls, [])


@contextmanager
def _no_clients():
    """Any attempt to build a Square client or read a token fails the test."""
    with (
        patch.object(cs, "create_client", side_effect=_strict("create_client")),
        patch.object(cs, "create_square_client", side_effect=_strict("create_square_client")),
        patch.object(cs, "resolve_merchant_access_token", side_effect=_strict("resolve_merchant_access_token")),
        patch.object(cs, "load_source", side_effect=_strict("load_source")),
        patch.object(cs, "translate_binding", side_effect=_strict("translate_binding")),
    ):
        yield


class MainGuardTests(unittest.TestCase):
    def _with_snapshot(self, tmp):
        cs.export_snapshot(_prod_square(), "mosa_prod_test", source=SOURCE)

    # 1. Identity guard.
    def test_writes_refuse_the_snapshots_source_merchant(self):
        commands = (
            ["replay", "--apply"],
            ["translate-binding"],
            ["copy-counts", "--apply"],
        )
        with _snapshot_dir() as tmp:
            self._with_snapshot(tmp)
            for command in commands:
                with self.subTest(command=command), _sandbox_settings(), _no_clients():
                    exit_code = cs.main(
                        [command[0], "--account", "mosa_prod_test", "--merchant", PROD_MERCHANT,
                         "--environment", "sandbox", "--location-id", SANDBOX_LOCATION, *command[1:]]
                    )
                    self.assertEqual(exit_code, 1)

    def test_writes_refuse_when_the_snapshot_is_missing(self):
        commands = (["replay", "--apply"], ["translate-binding"], ["copy-counts", "--apply"])
        with _snapshot_dir():
            for command in commands:
                with self.subTest(command=command), _sandbox_settings(), _no_clients():
                    exit_code = cs.main(
                        [command[0], "--account", "mosa_prod_test", "--merchant", SANDBOX_MERCHANT,
                         "--environment", "sandbox", "--location-id", SANDBOX_LOCATION, *command[1:]]
                    )
                    self.assertEqual(exit_code, 1)

    def test_load_source_makes_dynamodb_decimals_writable(self):
        from decimal import Decimal

        stored = {"version": Decimal("7"), "mapping": {**PROD_MAPPING, "note_count": Decimal("2")}}
        context = SimpleNamespace(location_id=PROD_LOCATION)
        with (
            patch.object(cs, "get_merchant_context", return_value=context),
            patch.object(cs, "get_active_catalog_binding", return_value=stored),
        ):
            source = cs.load_source("production", PROD_MERCHANT)
        self.assertEqual(source["binding_version"], 7)
        json.dumps(source)

    def test_a_different_target_merchant_passes_the_identity_guard(self):
        with _snapshot_dir() as tmp:
            self._with_snapshot(tmp)
            with (
                _sandbox_settings(),
                patch.object(cs, "translate_binding", return_value=(0, 1)) as mock_translate,
            ):
                exit_code = cs.main(
                    ["translate-binding", "--account", "mosa_prod_test", "--merchant", SANDBOX_MERCHANT,
                     "--environment", "sandbox", "--location-id", SANDBOX_LOCATION]
                )
        self.assertEqual(exit_code, 0)
        mock_translate.assert_called_once()

    # 2. Gitignore guard.
    def test_git_confirms_prod_snapshot_names_are_ignored_and_others_are_not(self):
        repo = Path(__file__).resolve().parents[1]
        snapshots = repo / "data" / "catalog_snapshots"
        for name in ("mosa_prod_2026-11-19.json", "mosa_prod_2026-11-19.idmap.json", "mosa_prod_2026-11-19.counts.json"):
            self.assertTrue(cs.is_gitignored(snapshots / name), name)
        self.assertFalse(cs.is_gitignored(snapshots / "fresh_copy_test.json"))

    def test_production_export_refuses_a_file_that_is_not_gitignored(self):
        for command in ("export", "export-counts"):
            with self.subTest(command=command), _snapshot_dir() as tmp, _no_clients():
                with patch.object(cs, "is_gitignored", return_value=False):
                    exit_code = cs.main(
                        [command, "--account", "mosa_prod_test", "--merchant", PROD_MERCHANT,
                         "--environment", "production"]
                    )
                self.assertEqual(exit_code, 1)
                self.assertEqual(list(tmp.iterdir()), [])

    def test_production_export_writes_when_the_file_is_gitignored(self):
        with _snapshot_dir() as tmp:
            with (
                patch.object(cs, "is_gitignored", return_value=True) as mock_ignored,
                patch.object(cs, "load_source", return_value=SOURCE),
                patch.object(cs, "create_client", return_value=_prod_square()),
            ):
                exit_code = cs.main(
                    ["export", "--account", "mosa_prod_test", "--merchant", PROD_MERCHANT,
                     "--environment", "production"]
                )
            written = (tmp / "mosa_prod_test.json").exists()
        self.assertEqual(exit_code, 0)
        self.assertTrue(written)
        mock_ignored.assert_called_once_with(tmp / "mosa_prod_test.json")

    # 3. main()-level production guard for replay.
    def test_main_replay_against_production_exits_before_any_client_or_token(self):
        with _snapshot_dir() as tmp:
            self._with_snapshot(tmp)
            for extra in ([], ["--apply"]):
                with self.subTest(extra=extra), _sandbox_settings(), _no_clients():
                    exit_code = cs.main(
                        ["replay", "--account", "mosa_prod_test", "--merchant", SANDBOX_MERCHANT,
                         "--environment", "production", *extra]
                    )
                    self.assertEqual(exit_code, 1)

    # 4. Production always names a merchant.
    def test_production_requires_merchant(self):
        for command in ("export", "export-counts", "verify"):
            with self.subTest(command=command), _snapshot_dir(), _no_clients():
                with patch.object(cs, "is_gitignored", return_value=True):
                    exit_code = cs.main([command, "--account", "mosa_prod_test", "--environment", "production"])
                self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
