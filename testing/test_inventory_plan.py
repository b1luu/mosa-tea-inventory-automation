import unittest

from app.inventory_plan import (
    build_inventory_plan_from_order_summaries,
    build_inventory_plan_from_order_summary,
)
from app.order_processor import apply_inventory_plan
from testing.order_projection_utils import load_scenario_order


class InventoryPlanTests(unittest.TestCase):
    def test_build_inventory_plan_from_order_summary_is_pure_and_deterministic(self):
        order_summary = load_scenario_order("tgy_tea_100_sugar")

        plan = build_inventory_plan_from_order_summary(
            order_summary,
            occurred_at="2026-04-03T20:00:00Z",
        )

        self.assertTrue(plan.can_apply)
        self.assertIsNone(plan.blocking_reason)
        self.assertEqual(plan.projected_orders[0]["order_id"], "testing:tgy_tea_100_sugar")
        self.assertEqual(len(plan.inventory_request["changes"]), 4)
        self.assertEqual(
            plan.inventory_request["changes"][0]["adjustment"]["occurred_at"],
            "2026-04-03T20:00:00Z",
        )

    def test_build_inventory_plan_blocks_apply_when_line_item_cannot_be_projected(self):
        plan = build_inventory_plan_from_order_summaries(
            [
                {
                    "id": "order-1",
                    "location_id": "LB1MECVA7EZ8Z",
                    "state": "COMPLETED",
                    "line_items": [
                        {
                            "quantity": "1",
                            "name": "Broken item",
                            "modifiers": [],
                        }
                    ],
                }
            ],
            occurred_at="2026-04-03T20:00:00Z",
        )

        self.assertFalse(plan.can_apply)
        self.assertIn("skipped during projection", plan.blocking_reason)
        self.assertEqual(len(plan.skipped_line_items), 1)

    def test_apply_inventory_plan_returns_blocking_error_without_client_call(self):
        plan = build_inventory_plan_from_order_summaries(
            [
                {
                    "id": "order-1",
                    "location_id": "LB1MECVA7EZ8Z",
                    "state": "COMPLETED",
                    "line_items": [
                        {
                            "quantity": "1",
                            "name": "Broken item",
                            "modifiers": [],
                        }
                    ],
                }
            ],
            occurred_at="2026-04-03T20:00:00Z",
        )

        self.assertEqual(
            apply_inventory_plan(plan, apply_changes=True),
            {"error": plan.blocking_reason},
        )

    def test_apply_inventory_plan_executes_inventory_request(self):
        order_summary = load_scenario_order("tgy_tea_100_sugar")
        plan = build_inventory_plan_from_order_summary(
            order_summary,
            occurred_at="2026-04-03T20:00:00Z",
        )

        inventory_client = type(
            "Inventory",
            (),
            {
                "batch_create_changes": staticmethod(
                    lambda **kwargs: type(
                        "Response",
                        (),
                        {"model_dump": staticmethod(lambda mode="json": {"ok": True})},
                    )()
                )
            },
        )()
        client = type("Client", (), {"inventory": inventory_client})()

        result = apply_inventory_plan(plan, apply_changes=True, client=client)

        self.assertEqual(result, {"ok": True})

    def test_apply_inventory_plan_rewrites_inventory_ids_with_binding(self):
        order_summary = load_scenario_order("tgy_tea_100_sugar")
        plan = build_inventory_plan_from_order_summary(
            order_summary,
            occurred_at="2026-04-03T20:00:00Z",
        )
        captured = {}

        inventory_client = type(
            "Inventory",
            (),
            {
                "batch_create_changes": staticmethod(
                    lambda **kwargs: (
                        captured.setdefault("request", kwargs),
                        type(
                            "Response",
                            (),
                            {"model_dump": staticmethod(lambda mode="json": {"ok": True})},
                        )(),
                    )[1]
                )
            },
        )()
        client = type("Client", (), {"inventory": inventory_client})()
        binding = {
            "mapping": {
                "inventory_variation_ids": {
                    "tgy": "LIVE-TGY",
                    "sugar_syrup": "LIVE-SUGAR",
                    "u600_cup": "LIVE-CUP",
                    "small_straw": "LIVE-STRAW",
                }
            }
        }

        apply_inventory_plan(
            plan,
            apply_changes=True,
            client=client,
            binding=binding,
        )

        request = captured["request"]
        catalog_object_ids = [
            change["adjustment"]["catalog_object_id"]
            for change in request["changes"]
        ]
        self.assertEqual(
            catalog_object_ids,
            ["LIVE-TGY", "LIVE-SUGAR", "LIVE-CUP", "LIVE-STRAW"],
        )


if __name__ == "__main__":
    unittest.main()
