import copy
import unittest
from decimal import Decimal

from app.inventory_plan import (
    build_inventory_plan_from_order_summaries,
    build_inventory_plan_from_order_summary,
)
from app.order_processor import apply_inventory_plan, process_orders
from testing.order_projection_utils import load_fixture_order, load_scenario_order


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

    def test_apply_inventory_plan_refuses_write_without_explicit_client(self):
        # A plan with real changes must not write via the env token: requiring
        # an explicit client at the write site is the Part 3 guarantee.
        order_summary = load_scenario_order("tgy_tea_100_sugar")
        plan = build_inventory_plan_from_order_summary(
            order_summary,
            occurred_at="2026-04-03T20:00:00Z",
        )

        with self.assertRaises(ValueError):
            apply_inventory_plan(plan, apply_changes=True, client=None)

    def test_process_orders_refuses_write_without_explicit_client(self):
        # Guard fires before any Square call, so no order lookup is attempted.
        with self.assertRaises(ValueError):
            process_orders(["order-1"], apply_changes=True, client=None)

    def test_process_orders_allows_projection_without_client(self):
        # apply_changes=False is read-only projection and may use the env client;
        # it must NOT raise. (Guards the guard: ensures we only block writes.)
        order_summary = load_scenario_order("tgy_tea_100_sugar")
        plan = build_inventory_plan_from_order_summary(
            order_summary,
            occurred_at="2026-04-03T20:00:00Z",
        )
        # apply_inventory_plan with apply_changes=False returns None before any
        # client is needed.
        self.assertIsNone(apply_inventory_plan(plan, apply_changes=False, client=None))

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


OCCURRED_AT = "2026-04-03T20:00:00Z"


def _matcha_boba_order():
    """Matcha Latte with Boba and No Sugar, in the normalized order-summary shape."""
    return load_fixture_order("completed_matcha_latte_boba")


def _with_line_item(order_summary, **fields):
    mutated = copy.deepcopy(order_summary)
    mutated["line_items"][0].update(fields)
    return mutated


def _plan(order_summary):
    return build_inventory_plan_from_order_summaries([order_summary], occurred_at=OCCURRED_AT)


def _usage_amount(plan, inventory_key):
    return sum(
        (usage["total_amount"] for usage in plan.combined_usage if usage["inventory_key"] == inventory_key),
        Decimal("0"),
    )


class OrderSummaryContractTests(unittest.TestCase):
    """How the planner handles malformed or unusual order-summary payloads.

    Production summaries come only from order_loader.normalize_square_order_for_inventory_plan,
    so most of these shapes can't reach the worker today. The tests pin the contract so a
    change to the normalizer, a script, or a fixture can't make a bad payload deduct wrongly.

    Tests marked expectedFailure describe the intended behavior for known gaps. When a gap is
    fixed, unittest reports an "unexpected success": remove the decorator then.
    """

    def test_baseline_fixture_applies(self):
        plan = _plan(_matcha_boba_order())

        self.assertTrue(plan.can_apply)
        self.assertEqual(_usage_amount(plan, "boba"), Decimal("100"))

    def test_line_items_none_is_treated_as_empty(self):
        order_summary = {**_matcha_boba_order(), "line_items": None}

        plan = _plan(order_summary)

        self.assertTrue(plan.can_apply)
        self.assertEqual(plan.skipped_line_items, [])
        self.assertEqual(plan.inventory_request["changes"], [])

    def test_modifiers_none_blocks_instead_of_raising(self):
        plan = _plan(_with_line_item(_matcha_boba_order(), modifiers=None))

        self.assertFalse(plan.can_apply)
        self.assertEqual(plan.inventory_request["changes"], [])

    def test_modifier_without_catalog_object_id_is_ignored_not_raised(self):
        order_summary = copy.deepcopy(_matcha_boba_order())
        for modifier in order_summary["line_items"][0]["modifiers"]:
            modifier.pop("catalog_object_id")

        plan = _plan(order_summary)

        # The required sugar modifier is now unreadable, so the order blocks.
        self.assertFalse(plan.can_apply)
        self.assertEqual(plan.skipped_line_items[0]["modifier_ids"], [])

    def test_invalid_quantity_blocks_the_order(self):
        for quantity in (None, "abc", ""):
            with self.subTest(quantity=quantity):
                plan = _plan(_with_line_item(_matcha_boba_order(), quantity=quantity))

                self.assertFalse(plan.can_apply)
                self.assertEqual(plan.inventory_request["changes"], [])

    def test_missing_quantity_blocks_the_order(self):
        order_summary = copy.deepcopy(_matcha_boba_order())
        order_summary["line_items"][0].pop("quantity")

        plan = _plan(order_summary)

        self.assertFalse(plan.can_apply)

    @unittest.expectedFailure
    def test_invalid_quantity_reason_names_the_bad_value(self):
        # Gap: Decimal(str(None)) raises decimal.InvalidOperation, whose message is
        # "[<class 'decimal.ConversionSyntax'>]". That text lands in the daily-check email.
        plan = _plan(_with_line_item(_matcha_boba_order(), quantity=None))

        self.assertIn("quantity", plan.skipped_line_items[0]["reason"].lower())

    @unittest.expectedFailure
    def test_zero_quantity_line_item_blocks_instead_of_applying_nothing(self):
        # Gap: a line item that projects to no positive usage is dropped from the
        # Square request, yet the plan says can_apply=True, so the worker marks the
        # order applied with nothing deducted.
        plan = _plan(_with_line_item(_matcha_boba_order(), quantity="0"))

        self.assertFalse(plan.can_apply)

    @unittest.expectedFailure
    def test_negative_quantity_line_item_blocks_instead_of_applying_nothing(self):
        plan = _plan(_with_line_item(_matcha_boba_order(), quantity="-1"))

        self.assertFalse(plan.can_apply)

    @unittest.expectedFailure
    def test_order_wrapped_in_square_root_key_does_not_silently_apply(self):
        # Gap: a raw Square response shape ({"order": {...}}) has no top-level
        # line_items, so it plans as an empty order and would be marked applied.
        plan = _plan({"order": _matcha_boba_order()})

        self.assertFalse(plan.can_apply)

    @unittest.expectedFailure
    def test_modifier_quantity_scales_topping_usage(self):
        # Gap: _extract_line_items keeps modifier IDs only, so "Boba x2" rung as one
        # modifier with quantity 2 deducts one portion of boba.
        order_summary = copy.deepcopy(_matcha_boba_order())
        boba = next(
            modifier
            for modifier in order_summary["line_items"][0]["modifiers"]
            if modifier["name"] == "Boba"
        )
        boba["quantity"] = "2"

        plan = _plan(order_summary)

        self.assertEqual(_usage_amount(plan, "boba"), Decimal("200"))

    def test_line_item_quantity_scales_every_ingredient(self):
        single = _plan(_matcha_boba_order())
        double = _plan(_with_line_item(_matcha_boba_order(), quantity="2"))

        for usage in single.combined_usage:
            with self.subTest(inventory_key=usage["inventory_key"]):
                self.assertEqual(
                    _usage_amount(double, usage["inventory_key"]),
                    usage["total_amount"] * 2,
                )


if __name__ == "__main__":
    unittest.main()
