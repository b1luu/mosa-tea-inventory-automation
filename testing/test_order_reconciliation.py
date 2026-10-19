import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.order_reconciliation import (
    build_report,
    classify,
    explain,
    fetch_orders_for_day,
    format_day_lines,
    format_weekly_lines,
    needs_alert,
)


def _order(order_id, *, state="COMPLETED", source="Point of Sale", paid=True, due=0,
           created_at="2026-10-17T19:41:00.000Z", items=(("Matcha Latte", "1"),)):
    return SimpleNamespace(
        id=order_id,
        state=state,
        created_at=created_at,
        source=SimpleNamespace(name=source) if source else None,
        tenders=[object()] if paid else [],
        net_amount_due_money=SimpleNamespace(amount=due),
        line_items=[SimpleNamespace(name=name, quantity=quantity, modifiers=[]) for name, quantity in items],
    )


def _state(state):
    return {"processing_state": state}


def _bucket_of(buckets, order_id):
    return next(name for name, entries in buckets.items() if any(e["order_id"] == order_id for e in entries))


class ClassifyTests(unittest.TestCase):
    def test_each_bucket(self):
        orders = [
            _order("applied"),
            _order("blocked"),
            _order("failed"),
            _order("pending"),
            _order("processing"),
            _order("missed"),
            _order("cancelled-but-paid-again"),
            _order("open-paid-applied", state="OPEN", source="Square Online"),
            _order("reversed", state="CANCELED"),
            _order("draft", state="DRAFT", paid=False),
            _order("unpaid-open", state="OPEN", paid=False),
            _order("cancelled-unpaid", state="CANCELED", paid=False),
            _order("partly-paid", state="OPEN", due=500),
        ]
        records = {
            "applied": _state("applied"),
            "blocked": _state("blocked"),
            "failed": _state("failed"),
            "pending": _state("pending"),
            "processing": _state("processing"),
            "cancelled-but-paid-again": _state("cancelled_before_apply"),
            "open-paid-applied": _state("applied"),
            "reversed": _state("applied"),
        }

        buckets = classify(orders, records)

        expected = {
            "applied": "applied",
            "blocked": "blocked",
            "failed": "failed",
            "pending": "stuck",
            "processing": "stuck",
            "missed": "missed",
            "cancelled-but-paid-again": "missed",
            "open-paid-applied": "applied",
            "reversed": "reversed",
            "draft": "not_a_sale",
            "unpaid-open": "not_a_sale",
            "cancelled-unpaid": "not_a_sale",
            "partly-paid": "not_a_sale",
        }
        for order_id, bucket in expected.items():
            self.assertEqual(_bucket_of(buckets, order_id), bucket, order_id)

    def test_cancelled_before_apply_and_unpaid_is_not_a_sale(self):
        buckets = classify(
            [_order("x", state="CANCELED")], {"x": _state("cancelled_before_apply")}
        )
        self.assertEqual(_bucket_of(buckets, "x"), "not_a_sale")


class ReportTests(unittest.TestCase):
    def test_clean_day_needs_no_alert(self):
        report = build_report(date(2026, 10, 17), [_order("a")], {"a": _state("applied")})

        self.assertFalse(needs_alert(report))
        self.assertEqual(format_day_lines(report), [])
        self.assertEqual(report["totals"]["applied_items"], 1)

    def test_any_problem_needs_an_alert(self):
        report = build_report(date(2026, 10, 17), [_order("a")], {"a": _state("blocked")})

        self.assertTrue(needs_alert(report))
        self.assertEqual(report["totals"]["problems"], 1)

    def test_paid_not_deductible_alerts_only_at_three_per_channel(self):
        # A paid order the rule skips: COMPLETED/OPEN are deductible, so use an
        # unusual state that still carries a payment.
        def odd(order_id, source):
            return _order(order_id, state="DRAFT", source=source)

        two = build_report(date(2026, 10, 17), [odd("a", "Kiosk"), odd("b", "Kiosk"), odd("c", "Invoices")], {})
        three = build_report(date(2026, 10, 17), [odd(f"k{i}", "Kiosk") for i in range(3)], {})

        self.assertFalse(needs_alert(two))
        self.assertTrue(needs_alert(three))
        self.assertEqual(three["patterns"], {"Kiosk": 3})
        self.assertIn("  Kiosk: 3  (pattern threshold is 3)", format_day_lines(three))

    def test_problem_lines_show_pacific_time_order_and_reason(self):
        report = build_report(
            date(2026, 10, 17),
            [_order("o-1", source="DoorDash", created_at="2026-10-18T01:12:00.000Z",
                    items=(("TGY Special", "2"),))],
            {},
        )
        report["buckets"]["missed"][0].update(reason=None, would_apply_now=True)

        lines = format_day_lines(report)

        self.assertIn("MISSED (no processing record) (1)", lines)
        self.assertIn("   6:12 pm  DoorDash       2 x TGY Special", lines)
        self.assertIn("            would apply now: yes", lines)

    def test_weekly_lines_total_the_week(self):
        reports = [
            build_report(date(2026, 10, 12), [_order("a")], {"a": _state("applied")}),
            build_report(date(2026, 10, 13), [_order("b")], {"b": _state("blocked")}),
        ]

        lines = format_weekly_lines(reports)

        self.assertIn("clean", lines[0])
        self.assertIn("1 not deducted", lines[1])
        self.assertIn("2 orders", lines[-1])


class ExplainTests(unittest.TestCase):
    def test_records_reasons_from_the_dry_run(self):
        entries = [{"order_id": "o-1"}]
        dry_run = {
            "projected_orders": [],
            "skipped_line_items": [{"reason": "No recipe mapping found for sold variation 'X'."}],
            "skipped_orders": [],
        }
        with patch("app.order_reconciliation.process_orders", return_value=dry_run) as process_mock:
            explain(entries, client="client", binding="binding")

        process_mock.assert_called_once_with(["o-1"], apply_changes=False, client="client", binding="binding")
        self.assertEqual(entries[0]["reason"], "No recipe mapping found for sold variation 'X'.")
        self.assertFalse(entries[0]["would_apply_now"])

    def test_fixed_problem_reports_would_apply_now(self):
        entries = [{"order_id": "o-1"}]
        dry_run = {"projected_orders": [{"order_id": "o-1"}], "skipped_line_items": [], "skipped_orders": []}
        with patch("app.order_reconciliation.process_orders", return_value=dry_run):
            explain(entries, client=None, binding=None)

        self.assertIsNone(entries[0]["reason"])
        self.assertTrue(entries[0]["would_apply_now"])

    def test_dry_run_failure_is_recorded_not_raised(self):
        entries = [{"order_id": "o-1"}]
        with patch("app.order_reconciliation.process_orders", side_effect=RuntimeError("boom")):
            explain(entries, client=None, binding=None)

        self.assertEqual(entries[0]["reason"], "could not dry-run: boom")


class FetchOrdersTests(unittest.TestCase):
    def test_queries_the_pacific_day_and_keeps_only_that_day(self):
        calls = []
        orders = [
            _order("in-day", created_at="2026-10-18T06:59:59.999Z"),
            _order("next-day", created_at="2026-10-18T07:00:00.000Z"),
        ]

        def search(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(orders=orders, cursor=None)

        client = SimpleNamespace(orders=SimpleNamespace(search=search))

        result = fetch_orders_for_day(client, "LOC-1", date(2026, 10, 17))

        window = calls[0]["query"]["filter"]["date_time_filter"]["created_at"]
        self.assertEqual(window, {"start_at": "2026-10-17T07:00:00.000Z", "end_at": "2026-10-18T07:00:00.000Z"})
        self.assertEqual([order.id for order in result], ["in-day"])


if __name__ == "__main__":
    unittest.main()
