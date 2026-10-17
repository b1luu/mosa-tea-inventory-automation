"""Tests for :mod:`app.oauth_refresh_scheduler`.

The scheduler is deliberately AWS-free — takes an environment name, scans the
merchant store, refreshes tokens within threshold. These tests patch the three
merchant_store entry points the scheduler calls to isolate the scheduling
logic from persistence, so they run fast and deterministic without moto or a
real DB.
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from square.core.api_error import ApiError

from app.merchant_store import MerchantContext
from app.merchant_store_constants import (
    AUTH_SOURCE_MANUAL_TOKEN,
    AUTH_SOURCE_OAUTH,
)
from app.oauth_refresh_scheduler import refresh_expiring_tokens


def _ctx(merchant_id, environment="production", auth_mode=AUTH_SOURCE_OAUTH):
    return MerchantContext(
        environment=environment,
        merchant_id=merchant_id,
        status="active",
        auth_mode=auth_mode,
        location_id="LOC-1",
        writes_enabled=True,
        binding_version="1",
        display_name=f"Store {merchant_id}",
    )


def _auth(expires_at, has_refresh_token=True):
    return {
        "source": AUTH_SOURCE_OAUTH,
        "token_type": "bearer",
        "expires_at": expires_at,
        "short_lived": False,
        "refresh_token": "refresh-secret-value" if has_refresh_token else None,
        "scopes": ["INVENTORY_READ"],
        "updated_at": "2026-07-01T00:00:00Z",
    }


class OAuthRefreshSchedulerTests(unittest.TestCase):
    NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)

    def _patch_store(self, *, contexts, auth_by_merchant, refresh_result=None,
                     refresh_side_effect=None):
        """Patches the three merchant_store functions the scheduler depends on.
        Returns the refresh mock so tests can assert call counts / args."""
        contexts_patch = patch(
            "app.oauth_refresh_scheduler.list_merchant_contexts",
            return_value=contexts,
        )
        auth_patch = patch(
            "app.oauth_refresh_scheduler.get_merchant_auth_record",
            side_effect=lambda env, mid: auth_by_merchant.get(mid),
        )
        refresh_patch = patch(
            "app.oauth_refresh_scheduler.refresh_oauth_merchant_access_token",
            return_value=refresh_result,
            side_effect=refresh_side_effect,
        )
        self.addCleanup(contexts_patch.stop)
        self.addCleanup(auth_patch.stop)
        self.addCleanup(refresh_patch.stop)
        contexts_patch.start()
        auth_patch.start()
        return refresh_patch.start()

    def test_far_future_expiry_is_skipped(self):
        far_future = (self.NOW + timedelta(days=25)).isoformat().replace("+00:00", "Z")
        refresh = self._patch_store(
            contexts=[_ctx("M1")],
            auth_by_merchant={"M1": _auth(far_future)},
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["total_merchants"], 1)
        self.assertEqual(result["refreshed"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["results"][0]["action"], "skipped_not_expiring")
        refresh.assert_not_called()

    def test_expiring_within_threshold_is_refreshed(self):
        near_expiry = (self.NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")
        new_expiry = (self.NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z")
        refresh = self._patch_store(
            contexts=[_ctx("M1")],
            auth_by_merchant={"M1": _auth(near_expiry)},
            refresh_result={**_auth(new_expiry), "expires_at": new_expiry},
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["refreshed"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["failed"], 0)
        entry = result["results"][0]
        self.assertEqual(entry["action"], "refreshed")
        self.assertEqual(entry["new_expires_at"], new_expiry)
        refresh.assert_called_once_with("production", "M1", force=True)

    def test_missing_auth_record_is_skipped_not_failed(self):
        refresh = self._patch_store(
            contexts=[_ctx("M1")],
            auth_by_merchant={},  # empty — no auth record for M1
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["results"][0]["action"], "skipped_no_auth_record")
        refresh.assert_not_called()

    def test_missing_refresh_token_is_a_failure_not_refreshed(self):
        # No refresh_token means the token will lapse and only a re-OAuth can
        # fix it, so it counts as a failure: the Lambda raises and the error
        # alarm emails the operator while there is still time.
        near_expiry = (self.NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")
        refresh = self._patch_store(
            contexts=[_ctx("M1")],
            auth_by_merchant={"M1": _auth(near_expiry, has_refresh_token=False)},
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["results"][0]["action"], "failed_no_refresh_token")
        refresh.assert_not_called()

    def test_dry_run_does_not_call_refresh(self):
        near_expiry = (self.NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")
        refresh = self._patch_store(
            contexts=[_ctx("M1")],
            auth_by_merchant={"M1": _auth(near_expiry)},
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW, dry_run=True,
        )

        self.assertEqual(result["would_refresh"], 1)
        self.assertEqual(result["refreshed"], 0)
        self.assertEqual(result["results"][0]["action"], "would_refresh_dry_run")
        refresh.assert_not_called()

    def test_environment_mismatch_is_filtered_out(self):
        # A sandbox merchant should not be considered during a production sweep,
        # even though list_merchant_contexts returns it.
        near_expiry = (self.NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")
        refresh = self._patch_store(
            contexts=[
                _ctx("M-PROD", environment="production"),
                _ctx("M-SANDBOX", environment="sandbox"),
            ],
            auth_by_merchant={
                "M-PROD": _auth(near_expiry),
                "M-SANDBOX": _auth(near_expiry),
            },
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["total_merchants"], 1)  # only M-PROD
        self.assertEqual(result["refreshed"], 1)
        refresh.assert_called_once_with("production", "M-PROD", force=True)

    def test_non_oauth_merchant_is_filtered_out(self):
        # Merchants authed via manual token can't be refreshed — nothing to do.
        near_expiry = (self.NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")
        refresh = self._patch_store(
            contexts=[
                _ctx("M-OAUTH", auth_mode=AUTH_SOURCE_OAUTH),
                _ctx("M-MANUAL", auth_mode=AUTH_SOURCE_MANUAL_TOKEN),
            ],
            auth_by_merchant={
                "M-OAUTH": _auth(near_expiry),
                "M-MANUAL": _auth(near_expiry),
            },
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["total_merchants"], 1)  # only OAuth merchant
        self.assertEqual(result["refreshed"], 1)
        refresh.assert_called_once_with("production", "M-OAUTH", force=True)

    def test_one_failure_does_not_stop_the_batch(self):
        near_expiry = (self.NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")
        new_expiry = (self.NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z")

        # M2 will raise; M1 and M3 succeed.
        def refresh_impl(env, merchant_id, *, force):
            if merchant_id == "M2":
                raise ValueError("Refresh token has been revoked by Square.")
            return {"expires_at": new_expiry}

        refresh = self._patch_store(
            contexts=[_ctx("M1"), _ctx("M2"), _ctx("M3")],
            auth_by_merchant={
                "M1": _auth(near_expiry),
                "M2": _auth(near_expiry),
                "M3": _auth(near_expiry),
            },
            refresh_side_effect=refresh_impl,
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["total_merchants"], 3)
        self.assertEqual(result["refreshed"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(refresh.call_count, 3)

        # M2 got captured with the error string.
        failed = [r for r in result["results"] if r["action"] == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["merchant_id"], "M2")
        self.assertIn("revoked", failed[0]["error"].lower())

    def test_square_api_error_captured_as_failure(self):
        near_expiry = (self.NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")
        refresh = self._patch_store(
            contexts=[_ctx("M1")],
            auth_by_merchant={"M1": _auth(near_expiry)},
            refresh_side_effect=ApiError(status_code=502, body="Bad Gateway"),
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["refreshed"], 0)
        self.assertEqual(result["results"][0]["action"], "failed")

    def test_summary_counts_add_up(self):
        # 4 merchants: 1 far-future skip, 1 near-expiry refresh,
        # 1 no-refresh-token failure, 1 refresh failure.
        far_future = (self.NOW + timedelta(days=25)).isoformat().replace("+00:00", "Z")
        near_expiry = (self.NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z")

        def refresh_impl(env, merchant_id, *, force):
            if merchant_id == "M-FAIL":
                raise ValueError("something broke")
            return {"expires_at": far_future}

        self._patch_store(
            contexts=[
                _ctx("M-SAFE"),
                _ctx("M-REFRESH"),
                _ctx("M-NO-RT"),
                _ctx("M-FAIL"),
            ],
            auth_by_merchant={
                "M-SAFE":     _auth(far_future),
                "M-REFRESH":  _auth(near_expiry),
                "M-NO-RT":    _auth(near_expiry, has_refresh_token=False),
                "M-FAIL":     _auth(near_expiry),
            },
            refresh_side_effect=refresh_impl,
        )

        result = refresh_expiring_tokens(
            environment="production", threshold_days=10, now=self.NOW,
        )

        self.assertEqual(result["total_merchants"], 4)
        self.assertEqual(result["refreshed"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["failed"], 2)
        # Counts sum to total (dry-run isn't in play here).
        self.assertEqual(
            result["refreshed"] + result["skipped"] + result["failed"],
            result["total_merchants"],
        )

    def test_default_threshold_is_ten_days(self):
        # Explicit check on the defaulted 10-day threshold — the design
        # decision from Phase 1. If someone changes it accidentally, this
        # test flags it.
        near_but_outside_default = (self.NOW + timedelta(days=11)).isoformat().replace("+00:00", "Z")
        refresh = self._patch_store(
            contexts=[_ctx("M1")],
            auth_by_merchant={"M1": _auth(near_but_outside_default)},
        )

        result = refresh_expiring_tokens(environment="production", now=self.NOW)

        self.assertEqual(result["threshold_days"], 10)
        self.assertEqual(result["skipped"], 1)
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
