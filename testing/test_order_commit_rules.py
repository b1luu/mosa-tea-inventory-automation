import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.order_commit_rules import (
    PAID_ORDER_HOLD_SECONDS,
    fetch_is_paid_in_full,
    is_cancelled_order,
    is_committable_order,
    is_paid_in_full,
)


def _order(state="OPEN", source="Kiosk", tenders=1, amount_due=0):
    return SimpleNamespace(
        state=state,
        source=SimpleNamespace(name=source) if source else None,
        tenders=[object()] * tenders,
        net_amount_due_money=SimpleNamespace(amount=amount_due) if amount_due is not None else None,
    )


class OrderCommitRuleTests(unittest.TestCase):
    def test_paid_open_order_commits_from_any_channel(self):
        for source in ("Kiosk", "Square Online", "DoorDash", "Point of Sale", None):
            self.assertTrue(is_paid_in_full(_order(source=source)), source)
            self.assertTrue(is_committable_order(_order(source=source)), source)

    def test_open_order_with_no_tender_does_not_commit(self):
        self.assertFalse(is_committable_order(_order(tenders=0)))

    def test_open_order_with_amount_still_due_does_not_commit(self):
        self.assertFalse(is_committable_order(_order(amount_due=650)))

    def test_cancelled_or_draft_order_does_not_commit(self):
        for state in ("CANCELED", "DRAFT"):
            self.assertFalse(is_committable_order(_order(state=state)), state)

    def test_completed_order_commits_even_without_a_tender(self):
        self.assertTrue(is_committable_order(_order(state="COMPLETED", tenders=0)))

    def test_missing_amount_due_falls_back_to_tender_check(self):
        self.assertTrue(is_paid_in_full(_order(amount_due=None)))

    def test_cancelled_order_is_recognised(self):
        self.assertTrue(is_cancelled_order(_order(state="CANCELED")))
        self.assertFalse(is_cancelled_order(_order()))

    def test_hold_fits_within_the_sqs_delay_limit(self):
        self.assertLessEqual(PAID_ORDER_HOLD_SECONDS, 900)

    def test_fetch_reads_token_without_refreshing(self):
        order = _order(source="Square Online")
        client = SimpleNamespace(orders=SimpleNamespace(get=lambda order_id: SimpleNamespace(order=order)))
        with (
            patch("app.order_commit_rules.resolve_merchant_access_token", return_value="tok") as token_mock,
            patch("app.order_commit_rules.create_square_client", return_value=client),
        ):
            self.assertTrue(fetch_is_paid_in_full("production", "M-1", "order-1"))

        token_mock.assert_called_once_with("production", "M-1", refresh_if_needed=False)

    def test_fetch_without_token_raises_so_square_redelivers(self):
        with patch("app.order_commit_rules.resolve_merchant_access_token", return_value=None):
            with self.assertRaisesRegex(ValueError, "No Square access token"):
                fetch_is_paid_in_full("production", "M-1", "order-1")


if __name__ == "__main__":
    unittest.main()
