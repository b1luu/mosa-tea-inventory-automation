import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.lambda_binding_coverage_check import lambda_handler
from app.order_reconciliation import build_report
from app.merchant_store import MerchantContext


def _merchant_context(
    merchant_id,
    *,
    environment="sandbox",
    display_name=None,
    location_id="LOC-1",
    writes_enabled=False,
    binding_version=2,
):
    return MerchantContext(
        environment=environment,
        merchant_id=merchant_id,
        status="active",
        auth_mode="oauth",
        location_id=location_id,
        writes_enabled=writes_enabled,
        binding_version=binding_version,
        display_name=display_name,
    )


def _report(
    *,
    blocking_issue_count=0,
    unmapped_live_variations=None,
    unmapped_live_modifiers=None,
    warning_count=0,
):
    return {
        "summary": {
            "ready_for_approval": blocking_issue_count == 0,
            "blocking_issue_count": blocking_issue_count,
            "warning_count": warning_count,
        },
        "sold_variations": {
            "unmapped_live_variations": list(unmapped_live_variations or []),
        },
        "modifiers": {
            "unmapped_live_modifiers": list(unmapped_live_modifiers or []),
        },
    }


TUESDAY = date(2026, 10, 20)
MONDAY = date(2026, 10, 19)


def _clean_reconciliation(day=date(2026, 10, 19)):
    return build_report(day, [], {})


def _square_order(order_id, *, state="COMPLETED", source="Kiosk", created_at="2026-10-19T19:41:00.000Z"):
    return SimpleNamespace(
        id=order_id,
        state=state,
        created_at=created_at,
        source=SimpleNamespace(name=source),
        tenders=[object()],
        net_amount_due_money=SimpleNamespace(amount=0),
        line_items=[SimpleNamespace(name="Momo Frost", quantity="1", modifiers=[])],
    )


class BindingCoverageCheckLambdaTests(unittest.TestCase):
    def setUp(self):
        # Default every test to a clean reconciliation on a non-Monday, so the
        # coverage tests below stay about coverage.
        for target, kwargs in (
            ("app.lambda_binding_coverage_check.shop_today", {"return_value": TUESDAY}),
            (
                "app.lambda_binding_coverage_check.run_daily_reconciliation",
                {"side_effect": lambda merchant_context, day: _clean_reconciliation(day)},
            ),
            ("app.lambda_binding_coverage_check.run_weekly_summary", {"return_value": []}),
        ):
            patcher = patch(target, **kwargs)
            setattr(self, target.rsplit(".", 1)[1] + "_mock", patcher.start())
            self.addCleanup(patcher.stop)
    def test_returns_clean_without_publishing_when_all_merchants_are_covered(self):
        merchants = [
            _merchant_context("merchant-1", display_name="Tea Shop"),
            _merchant_context("merchant-2", display_name="Cafe"),
        ]

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report",
                side_effect=[_report(), _report()],
            ),
            patch(
                "app.lambda_binding_coverage_check._publish_summary_notification"
            ) as publish_mock,
        ):
            result = lambda_handler({}, None)

        self.assertEqual(result["checked_merchant_count"], 2)
        self.assertEqual(result["issue_merchant_count"], 0)
        self.assertEqual(result["error_merchant_count"], 0)
        self.assertFalse(result["published_alert"])
        publish_mock.assert_not_called()

    def test_publishes_one_summary_for_multiple_merchants_with_findings(self):
        merchants = [
            _merchant_context("merchant-1", display_name="Tea Shop", location_id="LOC-1"),
            _merchant_context("merchant-2", display_name="Cafe", location_id="LOC-2"),
        ]

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report",
                side_effect=[
                    _report(blocking_issue_count=2),
                    _report(unmapped_live_variations=[{"id": "LIVE-SOLD-3"}]),
                ],
            ),
            patch(
                "app.lambda_binding_coverage_check.get_alarm_notification_topic_arn",
                return_value="arn:aws:sns:us-west-2:123456789012:mosa-tea-ops",
            ),
            patch(
                "app.lambda_binding_coverage_check._publish_summary_notification"
            ) as publish_mock,
        ):
            result = lambda_handler({}, None)

        self.assertTrue(result["published_alert"])
        self.assertEqual(result["issue_merchant_count"], 2)
        self.assertEqual(result["error_merchant_count"], 0)
        publish_mock.assert_called_once()
        topic_arn, checked_count, issue_summaries, error_summaries = publish_mock.call_args.args
        self.assertEqual(topic_arn, "arn:aws:sns:us-west-2:123456789012:mosa-tea-ops")
        self.assertEqual(checked_count, 2)
        self.assertEqual(len(issue_summaries), 2)
        self.assertEqual(issue_summaries[0]["blocking_issue_count"], 2)
        self.assertEqual(issue_summaries[1]["unmapped_live_variation_count"], 1)
        self.assertEqual(error_summaries, [])

    def test_missing_location_is_reported_as_an_evaluation_error(self):
        merchants = [
            _merchant_context("merchant-1", display_name="Tea Shop", location_id=None),
        ]

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report"
            ) as report_mock,
            patch(
                "app.lambda_binding_coverage_check.get_alarm_notification_topic_arn",
                return_value="arn:aws:sns:us-west-2:123456789012:mosa-tea-ops",
            ),
            patch(
                "app.lambda_binding_coverage_check._publish_summary_notification"
            ) as publish_mock,
        ):
            result = lambda_handler({}, None)

        report_mock.assert_not_called()
        self.assertTrue(result["published_alert"])
        self.assertEqual(result["issue_merchant_count"], 0)
        self.assertEqual(result["error_merchant_count"], 1)
        self.assertEqual(result["errors"][0]["error_type"], "ValueError")
        publish_mock.assert_called_once()

    def test_publish_requires_topic_when_findings_exist(self):
        merchants = [_merchant_context("merchant-1", display_name="Tea Shop")]

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report",
                return_value=_report(blocking_issue_count=1),
            ),
            patch(
                "app.lambda_binding_coverage_check.get_alarm_notification_topic_arn",
                return_value=None,
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "ALARM_NOTIFICATION_TOPIC_ARN must be set",
            ):
                lambda_handler({}, None)


    def test_unmapped_modifier_alone_publishes_and_names_it(self):
        merchants = [_merchant_context("merchant-1", display_name="Tea Shop")]

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report",
                return_value=_report(
                    unmapped_live_modifiers=[{"id": "LIVE-OAT", "name": "Sub w/ Oat Milk"}],
                    warning_count=1,
                ),
            ),
            patch(
                "app.lambda_binding_coverage_check.get_alarm_notification_topic_arn",
                return_value="arn:aws:sns:us-west-2:123456789012:mosa-tea-ops",
            ),
            patch("app.lambda_binding_coverage_check._create_sns_client") as sns_factory,
        ):
            result = lambda_handler({}, None)

        self.assertTrue(result["published_alert"])
        self.assertEqual(result["issues"][0]["unmapped_live_modifier_count"], 1)
        message = sns_factory.return_value.publish.call_args.kwargs["Message"]
        self.assertIn("unmapped_live_modifier_count=1", message)
        self.assertIn("unmapped: Sub w/ Oat Milk", message)

    def test_reconciliation_problem_alone_publishes_combined_email(self):
        merchants = [_merchant_context("merchant-1", display_name="Mosa Tea")]
        problem = build_report(
            date(2026, 10, 19),
            [_square_order("order-blocked")],
            {"order-blocked": {"processing_state": "blocked"}},
        )
        problem["buckets"]["blocked"][0].update(reason="No recipe mapping found", would_apply_now=False)
        self.run_daily_reconciliation_mock.side_effect = None
        self.run_daily_reconciliation_mock.return_value = problem

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report",
                return_value=_report(),
            ),
            patch(
                "app.lambda_binding_coverage_check.get_alarm_notification_topic_arn",
                return_value="arn:aws:sns:us-west-2:123456789012:mosa-tea-ops",
            ),
            patch("app.lambda_binding_coverage_check._create_sns_client") as sns_factory,
        ):
            result = lambda_handler({}, None)

        self.assertTrue(result["published_alert"])
        self.run_daily_reconciliation_mock.assert_called_once_with(merchants[0], date(2026, 10, 19))
        publish = sns_factory.return_value.publish
        publish.assert_called_once()
        self.assertEqual(
            publish.call_args.kwargs["Subject"], "Mosa Tea daily check (Oct 19): 1 order not deducted"
        )
        message = publish.call_args.kwargs["Message"]
        self.assertIn("BLOCKED (1)", message)
        self.assertIn("order order-blocked", message)
        self.assertIn("reason: No recipe mapping found", message)
        self.assertIn("would apply now: no", message)

    def test_reconciliation_error_is_reported_without_stopping_coverage(self):
        merchants = [_merchant_context("merchant-1", display_name="Mosa Tea")]
        self.run_daily_reconciliation_mock.side_effect = RuntimeError("Square timeout")

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report",
                return_value=_report(),
            ) as coverage_mock,
            patch(
                "app.lambda_binding_coverage_check.get_alarm_notification_topic_arn",
                return_value="arn:aws:sns:us-west-2:123456789012:mosa-tea-ops",
            ),
            patch("app.lambda_binding_coverage_check._create_sns_client"),
        ):
            result = lambda_handler({}, None)

        coverage_mock.assert_called_once()
        self.assertEqual(result["errors"][0]["stage"], "order_reconciliation")
        self.assertTrue(result["published_alert"])

    def test_monday_sends_weekly_summary_even_when_clean(self):
        merchants = [_merchant_context("merchant-1", display_name="Mosa Tea")]
        self.shop_today_mock.return_value = MONDAY
        self.run_weekly_summary_mock.return_value = [
            _clean_reconciliation(date(2026, 10, 12 + offset)) for offset in range(7)
        ]

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report",
                return_value=_report(),
            ),
            patch(
                "app.lambda_binding_coverage_check.get_alarm_notification_topic_arn",
                return_value="arn:aws:sns:us-west-2:123456789012:mosa-tea-ops",
            ),
            patch("app.lambda_binding_coverage_check._create_sns_client") as sns_factory,
        ):
            result = lambda_handler({}, None)

        self.assertTrue(result["weekly_summary_sent"])
        self.assertFalse(result["published_alert"])
        self.run_weekly_summary_mock.assert_called_once_with(merchants[0], date(2026, 10, 18))
        publish = sns_factory.return_value.publish
        publish.assert_called_once()
        self.assertEqual(
            publish.call_args.kwargs["Subject"], "Mosa Tea weekly check (Oct 12 to Oct 18): all clean"
        )
        self.assertIn("If this email stops arriving", publish.call_args.kwargs["Message"])

    def test_no_weekly_summary_on_other_days(self):
        merchants = [_merchant_context("merchant-1", display_name="Mosa Tea")]

        with (
            patch(
                "app.lambda_binding_coverage_check.list_merchant_contexts",
                return_value=merchants,
            ),
            patch(
                "app.lambda_binding_coverage_check.build_binding_coverage_report",
                return_value=_report(),
            ),
            patch("app.lambda_binding_coverage_check._create_sns_client") as sns_factory,
        ):
            result = lambda_handler({}, None)

        self.assertFalse(result["weekly_summary_sent"])
        self.run_weekly_summary_mock.assert_not_called()
        sns_factory.return_value.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
