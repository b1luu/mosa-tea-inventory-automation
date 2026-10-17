import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from app import usage_log_db
from app.binding_coverage_report import get_canonical_binding_targets
from app.inventory_plan import build_inventory_plan_from_order_summary
from app.order_inventory_projection import is_log_only_inventory_key, project_line_item_usage
from app.usage_log_store import list_usage, record_order_usage
from app.webhook_worker import _record_applied_usage

MATCHA_LATTE = "DX2LRA7T4EFSSFH6POETDJHY"
SUGAR_100 = "IDFKCCIPYGFA67OPJMJ3SQVO"
SUB_OAT_MILK = "NASUMFZKO4P5GWA5YZNGENJ3"


def _usage_by_key(projected):
    return {usage["inventory_key"]: usage["total_amount"] for usage in projected["usage"]}


class OatMilkSubstitutionTests(unittest.TestCase):
    def test_sub_oat_milk_replaces_milk_one_to_one(self):
        dairy = _usage_by_key(project_line_item_usage(MATCHA_LATTE, "1", [SUGAR_100]))
        oat = _usage_by_key(project_line_item_usage(MATCHA_LATTE, "1", [SUGAR_100, SUB_OAT_MILK]))

        self.assertEqual(dairy["milk"], Decimal("150"))
        self.assertNotIn("oat_milk", dairy)
        self.assertEqual(oat["oat_milk"], Decimal("150"))
        self.assertNotIn("milk", oat)
        self.assertEqual(oat["matcha"], dairy["matcha"])

    def test_oat_milk_is_log_only_and_never_sent_to_square(self):
        self.assertTrue(is_log_only_inventory_key("oat_milk"))
        self.assertFalse(is_log_only_inventory_key("milk"))

        plan = build_inventory_plan_from_order_summary(
            {
                "id": "order-1",
                "location_id": "LOC-1",
                "state": "COMPLETED",
                "created_at": "2026-10-17T18:00:00Z",
                "line_items": [
                    {
                        "uid": "li-1",
                        "name": "Matcha Latte",
                        "quantity": "2",
                        "catalog_object_id": MATCHA_LATTE,
                        "modifiers": [
                            {"uid": "m-1", "catalog_object_id": SUGAR_100},
                            {"uid": "m-2", "catalog_object_id": SUB_OAT_MILK},
                        ],
                    }
                ],
            }
        )

        self.assertTrue(plan.can_apply)
        self.assertIn("oat_milk", {usage["inventory_key"] for usage in plan.combined_usage})
        sent_ids = {change["adjustment"]["catalog_object_id"] for change in plan.inventory_request["changes"]}
        self.assertNotIn(None, sent_ids)
        self.assertEqual(plan.projected_orders[0]["created_at"], "2026-10-17T18:00:00Z")

    def test_binding_never_requires_a_log_only_key(self):
        targets = get_canonical_binding_targets()

        self.assertNotIn("oat_milk", targets["inventory_keys"])
        self.assertIn("milk", targets["inventory_keys"])
        self.assertIn(SUB_OAT_MILK, targets["modifier_ids"])


class UsageLogStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_patch = patch.object(usage_log_db, "DB_FILE", Path(self._tmp.name) / "usage_log.db")
        self._db_patch.start()
        self._env_patch = patch.dict("os.environ", {"USAGE_LOG_STORE_MODE": "sqlite"})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._db_patch.stop()
        self._tmp.cleanup()

    def _usage(self, key, amount, unit="ml"):
        return {"inventory_key": key, "inventory_unit": unit, "total_amount": Decimal(amount)}

    def test_records_one_row_per_ingredient_and_sums_line_items(self):
        rows = record_order_usage(
            "production", "M-1", "LOC-1", "order-1", "2026-10-17T18:00:00Z",
            [self._usage("oat_milk", "150"), self._usage("oat_milk", "150"), self._usage("matcha", "8.75", "g")],
        )

        self.assertEqual({row["inventory_key"]: row["amount"] for row in rows}, {"matcha": "8.75", "oat_milk": "300"})
        stored = list_usage("production", "M-1", "LOC-1", "oat_milk", "2026-10-17", "2026-10-18")
        self.assertEqual([(row["order_id"], row["amount"]) for row in stored], [("order-1", "300")])

    def test_retrying_an_order_overwrites_instead_of_double_counting(self):
        for _ in range(2):
            record_order_usage(
                "production", "M-1", "LOC-1", "order-1", "2026-10-17T18:00:00Z", [self._usage("oat_milk", "150")]
            )

        stored = list_usage("production", "M-1", "LOC-1", "oat_milk", "2026-10-17", "2026-10-18")
        self.assertEqual(len(stored), 1)

    def test_list_usage_respects_the_time_window(self):
        for order_id, sold_at in (("early", "2026-10-16T23:59:00Z"), ("in", "2026-10-17T09:00:00Z"), ("late", "2026-10-18T00:00:00Z")):
            record_order_usage("production", "M-1", "LOC-1", order_id, sold_at, [self._usage("oat_milk", "150")])

        stored = list_usage("production", "M-1", "LOC-1", "oat_milk", "2026-10-17", "2026-10-18")
        self.assertEqual([row["order_id"] for row in stored], ["in"])

    def test_order_with_usage_but_no_sale_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no sale time"):
            record_order_usage("production", "M-1", "LOC-1", "order-1", None, [self._usage("oat_milk", "150")])


class WorkerUsageLogTests(unittest.TestCase):
    def test_records_each_projected_orders_own_usage(self):
        context = {"environment": "production", "merchant_id": "M-1", "location_id": "LOC-1"}
        result = {
            "projected_orders": [
                {"order_id": "order-1", "location_id": "LOC-1", "created_at": "2026-10-17T18:00:00Z"},
                {"order_id": "order-2", "location_id": None, "created_at": "2026-10-17T18:05:00Z"},
            ],
            "projected_line_items": [
                {"order_id": "order-1", "usage": [{"inventory_key": "oat_milk"}]},
                {"order_id": "order-2", "usage": [{"inventory_key": "milk"}]},
            ],
        }

        with patch("app.webhook_worker.record_order_usage") as record_mock:
            _record_applied_usage(context, result)

        calls = [call.args for call in record_mock.call_args_list]
        self.assertEqual(
            calls,
            [
                ("production", "M-1", "LOC-1", "order-1", "2026-10-17T18:00:00Z", [{"inventory_key": "oat_milk"}]),
                ("production", "M-1", "LOC-1", "order-2", "2026-10-17T18:05:00Z", [{"inventory_key": "milk"}]),
            ],
        )


if __name__ == "__main__":
    unittest.main()
