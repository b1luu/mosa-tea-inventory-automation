import unittest
from decimal import Decimal

from scripts.receive_delivery import build_changes, find_unreceivable, idempotency_key, parse_quantities


class ReceiveDeliveryTests(unittest.TestCase):
    def test_parses_key_quantity_pairs(self):
        self.assertEqual(
            parse_quantities(["tgy=70", "barley=0.5"]),
            {"tgy": Decimal("70"), "barley": Decimal("0.5")},
        )

    def test_rejects_bad_input(self):
        for pairs in (["tgy"], ["tgy=abc"], ["tgy=0"], ["tgy=-3"], ["tgy=1", "tgy=2"], ["=5"]):
            with self.assertRaises(ValueError, msg=pairs):
                parse_quantities(pairs)

    def test_refuses_log_only_unknown_and_unbound_items(self):
        items = {"tgy": {}, "oat_milk": {"tracking": "log_only"}, "new_tea": {}}
        problems = find_unreceivable(
            {"tgy": 1, "oat_milk": 1, "new_tea": 1, "mystery": 1}, items, {"tgy": "LIVE-TGY"}
        )

        self.assertEqual(set(problems), {"oat_milk", "new_tea", "mystery"})
        self.assertIn("log-only", problems["oat_milk"])

    def test_changes_receive_stock_with_a_per_item_reference(self):
        changes = build_changes(
            {"tgy": Decimal("70")}, {"tgy": "LIVE-TGY"}, "LOC-1", "delivery-2026-10-21", "2026-10-21T20:00:00Z"
        )

        adjustment = changes[0]["adjustment"]
        self.assertEqual((adjustment["from_state"], adjustment["to_state"]), ("NONE", "IN_STOCK"))
        self.assertEqual(adjustment["quantity"], "70")
        self.assertEqual(adjustment["reference_id"], "delivery-2026-10-21:tgy")

    def test_idempotency_key_is_stable_per_delivery(self):
        self.assertEqual(idempotency_key("delivery-2026-10-21"), idempotency_key("delivery-2026-10-21"))
        self.assertNotEqual(idempotency_key("delivery-2026-10-21"), idempotency_key("delivery-2026-11-04"))


if __name__ == "__main__":
    unittest.main()
