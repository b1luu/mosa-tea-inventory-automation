import unittest
from unittest.mock import patch

from app.lambda_oauth_refresh import OAuthRefreshFailedError, lambda_handler


def _summary(*, failed=0, results=None):
    return {
        "environment": "production",
        "threshold_days": 10,
        "dry_run": False,
        "total_merchants": len(results or []),
        "refreshed": 0,
        "would_refresh": 0,
        "skipped": 0,
        "failed": failed,
        "results": list(results or []),
    }


class OAuthRefreshLambdaTests(unittest.TestCase):
    def _run(self, summary, event=None):
        with (
            patch("app.lambda_oauth_refresh.get_square_environment_name", return_value="production"),
            patch("app.lambda_oauth_refresh.refresh_expiring_tokens", return_value=summary) as refresh_mock,
        ):
            return lambda_handler(event, None), refresh_mock

    def test_returns_summary_when_nothing_failed(self):
        summary = _summary(results=[{"merchant_id": "M1", "action": "skipped_not_expiring"}])

        result, refresh_mock = self._run(summary)

        self.assertIs(result, summary)
        refresh_mock.assert_called_once_with(environment="production", dry_run=False)

    def test_raises_and_names_failed_merchants(self):
        summary = _summary(
            failed=2,
            results=[
                {"merchant_id": "M1", "action": "refreshed"},
                {"merchant_id": "M2", "action": "failed", "error": "boom"},
                {"merchant_id": "M3", "action": "failed_no_refresh_token"},
            ],
        )

        with self.assertRaisesRegex(OAuthRefreshFailedError, "2 merchant\\(s\\): M2, M3"):
            self._run(summary)

    def test_dry_run_is_passed_through(self):
        _, refresh_mock = self._run(_summary(), event={"dry_run": True})

        refresh_mock.assert_called_once_with(environment="production", dry_run=True)

    def test_scheduled_event_without_dry_run_flag_refreshes_for_real(self):
        _, refresh_mock = self._run(_summary(), event={"source": "aws.events"})

        refresh_mock.assert_called_once_with(environment="production", dry_run=False)


if __name__ == "__main__":
    unittest.main()
