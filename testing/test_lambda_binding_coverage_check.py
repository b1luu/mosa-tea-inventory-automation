import unittest
from unittest.mock import patch

from app.lambda_binding_coverage_check import lambda_handler
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


def _report(*, blocking_issue_count=0, unmapped_live_variations=None, warning_count=0):
    return {
        "summary": {
            "ready_for_approval": blocking_issue_count == 0,
            "blocking_issue_count": blocking_issue_count,
            "warning_count": warning_count,
        },
        "sold_variations": {
            "unmapped_live_variations": list(unmapped_live_variations or []),
        },
    }


class BindingCoverageCheckLambdaTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
