import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.order_commit_rules import (
    fetch_is_paid_kiosk_order,
    is_committable_order,
    is_paid_kiosk_order,
)


def _order(state="OPEN", source="Kiosk", tenders=1, amount_due=0):
    return SimpleNamespace(
        state=state,
        source=SimpleNamespace(name=source) if source else None,
        tenders=[object()] * tenders,
        net_amount_due_money=SimpleNamespace(amount=amount_due) if amount_due is not None else None,
    )


class OrderCommitRuleTests(unittest.TestCase):
    def test_paid_open_kiosk_order_commits(self):
        self.assertTrue(is_paid_kiosk_order(_order()))
        self.assertTrue(is_committable_order(_order()))

    def test_kiosk_order_with_no_tender_does_not_commit(self):
        self.assertFalse(is_committable_order(_order(tenders=0)))

    def test_kiosk_order_with_amount_still_due_does_not_commit(self):
        self.assertFalse(is_committable_order(_order(amount_due=650)))

    def test_paid_open_order_from_another_channel_does_not_commit(self):
        for source in ("Point of Sale", "Square Online", None):
            self.assertFalse(is_committable_order(_order(source=source)), source)

    def test_cancelled_or_draft_kiosk_order_does_not_commit(self):
        for state in ("CANCELED", "DRAFT"):
            self.assertFalse(is_committable_order(_order(state=state)), state)

    def test_completed_order_commits_from_any_channel(self):
        self.assertTrue(is_committable_order(_order(state="COMPLETED", source="Point of Sale", tenders=0)))

    def test_missing_amount_due_falls_back_to_tender_check(self):
        self.assertTrue(is_paid_kiosk_order(_order(amount_due=None)))

    def test_fetch_reads_token_without_refreshing(self):
        order = _order()
        client = SimpleNamespace(orders=SimpleNamespace(get=lambda order_id: SimpleNamespace(order=order)))
        with (
            patch("app.order_commit_rules.resolve_merchant_access_token", return_value="tok") as token_mock,
            patch("app.order_commit_rules.create_square_client", return_value=client),
        ):
            self.assertTrue(fetch_is_paid_kiosk_order("production", "M-1", "order-1"))

        token_mock.assert_called_once_with("production", "M-1", refresh_if_needed=False)

    def test_fetch_without_token_raises_so_square_redelivers(self):
        with patch("app.order_commit_rules.resolve_merchant_access_token", return_value=None):
            with self.assertRaisesRegex(ValueError, "No Square access token"):
                fetch_is_paid_kiosk_order("production", "M-1", "order-1")


if __name__ == "__main__":
    unittest.main()
