import unittest
from unittest.mock import patch

from app.order_loader import (
    load_order_summaries_for_processing,
    normalize_square_order_for_inventory_plan,
)


def _build_line_item():
    return type(
        "LineItem",
        (),
        {
            "uid": "li-1",
            "name": "Tie Guan Yin Oolong Tea",
            "quantity": "1",
            "catalog_object_id": "72KIPS2KHWEK6RAT452MAB2P",
            "modifiers": [
                type(
                    "Modifier",
                    (),
                    {
                        "uid": "mod-1",
                        "name": "100% Sugar",
                        "quantity": "1",
                        "catalog_object_id": "VEDNAO6LH5WQET6TQTJGSPOB",
                    },
                )()
            ],
        },
    )()


def _build_order(order_id="order-1", state="COMPLETED"):
    return type(
        "Order",
        (),
        {
            "id": order_id,
            "location_id": "LB1MECVA7EZ8Z",
            "state": state,
            "line_items": [_build_line_item()],
        },
    )()


class OrderLoaderTests(unittest.TestCase):
    def test_normalize_square_order_for_inventory_plan_keeps_only_needed_fields(self):
        normalized = normalize_square_order_for_inventory_plan(_build_order())

        self.assertEqual(normalized["id"], "order-1")
        self.assertEqual(normalized["state"], "COMPLETED")
        self.assertEqual(
            normalized["line_items"][0]["catalog_object_id"],
            "72KIPS2KHWEK6RAT452MAB2P",
        )
        self.assertEqual(
            normalized["line_items"][0]["modifiers"][0]["catalog_object_id"],
            "VEDNAO6LH5WQET6TQTJGSPOB",
        )

    def test_load_order_summaries_for_processing_returns_completed_unapplied_orders(self):
        client = type(
            "Client",
            (),
            {
                "orders": type(
                    "Orders",
                    (),
                    {
                        "get": staticmethod(
                            lambda order_id: type(
                                "Response",
                                (),
                                {"order": _build_order(order_id=order_id)},
                            )()
                        )
                    },
                )()
            },
        )()

        with patch(
            "app.order_loader.get_order_processing_state",
            return_value=None,
        ):
            order_summaries, skipped_orders = load_order_summaries_for_processing(
                ["order-1"],
                client=client,
            )

        self.assertEqual(skipped_orders, [])
        self.assertEqual(order_summaries[0]["id"], "order-1")

    def test_load_order_summaries_for_processing_skips_applied_orders(self):
        client = type(
            "Client",
            (),
            {
                "orders": type(
                    "Orders",
                    (),
                    {
                        "get": staticmethod(
                            lambda order_id: type(
                                "Response",
                                (),
                                {"order": _build_order(order_id=order_id)},
                            )()
                        )
                    },
                )()
            },
        )()

        with patch(
            "app.order_loader.get_order_processing_state",
            return_value="applied",
        ):
            order_summaries, skipped_orders = load_order_summaries_for_processing(
                ["order-1"],
                client=client,
            )

        self.assertEqual(order_summaries, [])
        self.assertEqual(skipped_orders[0]["reason"], "Order already processed")

    def test_load_order_summaries_for_processing_skips_non_completed_orders(self):
        client = type(
            "Client",
            (),
            {
                "orders": type(
                    "Orders",
                    (),
                    {
                        "get": staticmethod(
                            lambda order_id: type(
                                "Response",
                                (),
                                {"order": _build_order(order_id=order_id, state="OPEN")},
                            )()
                        )
                    },
                )()
            },
        )()

        with patch(
            "app.order_loader.get_order_processing_state",
            return_value=None,
        ):
            order_summaries, skipped_orders = load_order_summaries_for_processing(
                ["order-1"],
                client=client,
            )

        self.assertEqual(order_summaries, [])
        self.assertEqual(skipped_orders[0]["reason"], "Order is not COMPLETED")

    def test_load_order_summaries_for_processing_canonicalizes_ids_with_binding(self):
        client = type(
            "Client",
            (),
            {
                "orders": type(
                    "Orders",
                    (),
                    {
                        "get": staticmethod(
                            lambda order_id: type(
                                "Response",
                                (),
                                {
                                    "order": _build_order(order_id=order_id),
                                },
                            )()
                        )
                    },
                )()
            },
        )()
        binding = {
            "mapping": {
                "sold_variation_aliases": {
                    "72KIPS2KHWEK6RAT452MAB2P": "CANONICAL-SOLD-ID",
                },
                "modifier_aliases": {
                    "VEDNAO6LH5WQET6TQTJGSPOB": "CANONICAL-MOD-ID",
                },
            }
        }

        with patch(
            "app.order_loader.get_order_processing_state",
            return_value=None,
        ):
            order_summaries, skipped_orders = load_order_summaries_for_processing(
                ["order-1"],
                client=client,
                binding=binding,
            )

        self.assertEqual(skipped_orders, [])
        self.assertEqual(
            order_summaries[0]["line_items"][0]["catalog_object_id"],
            "CANONICAL-SOLD-ID",
        )
        self.assertEqual(
            order_summaries[0]["line_items"][0]["modifiers"][0]["catalog_object_id"],
            "CANONICAL-MOD-ID",
        )


if __name__ == "__main__":
    unittest.main()
