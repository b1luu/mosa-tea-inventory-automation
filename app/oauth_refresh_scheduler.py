"""Scheduled OAuth access-token refresh — the business logic.

Wraps the existing :func:`refresh_oauth_merchant_access_token` in a scan-and-refresh
loop over every active OAuth-connected merchant, so the token never comes close
to Square's 30-day expiry.

This module is deliberately AWS-free: takes an environment name, iterates the
merchant store, and returns a summary dict. The Lambda handler
(:mod:`app.lambda_oauth_refresh`) is a thin invocation wrapper on top so we can
unit-test the scheduling logic without spinning up moto or a real Lambda.

Semantics:
    - Only OAuth-authed, active merchants are considered.
    - A merchant is refreshed when its ``expires_at`` falls within
      ``threshold_days`` of ``now`` (default 10 days — see the design decisions
      in the OAuth auto-refresh plan).
    - Refresh failures (Square API errors, expired refresh_token, etc.) are
      captured per-merchant. One merchant's failure never stops the others.
    - Returns aggregate counts + per-merchant details for logging / alarming.

Callers must inspect the returned ``failed`` count and decide whether the
overall invocation should be treated as an error (the Lambda handler raises so
CloudWatch's Errors metric picks it up).
"""

from datetime import UTC, datetime, timedelta

from square.core.api_error import ApiError

from app.merchant_store import (
    get_merchant_auth_record,
    list_merchant_contexts,
    refresh_oauth_merchant_access_token,
)
from app.merchant_store_constants import (
    AUTH_SOURCE_OAUTH,
    MERCHANT_STATUS_ACTIVE,
)

_ACTION_REFRESHED = "refreshed"
_ACTION_WOULD_REFRESH = "would_refresh_dry_run"
_ACTION_SKIPPED_NOT_EXPIRING = "skipped_not_expiring"
_ACTION_SKIPPED_NO_AUTH = "skipped_no_auth_record"
_ACTION_FAILED_NO_REFRESH_TOKEN = "failed_no_refresh_token"
_ACTION_FAILED = "failed"


def _parse_iso(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _needs_refresh(expires_at_iso, threshold_seconds, now):
    expires_at = _parse_iso(expires_at_iso)
    if expires_at is None:
        return False
    return expires_at <= now + timedelta(seconds=threshold_seconds)


def refresh_expiring_tokens(
    *,
    environment,
    threshold_days=10,
    dry_run=False,
    now=None,
):
    """Refresh every OAuth access token that expires within ``threshold_days``.

    Args:
        environment: ``"sandbox"`` or ``"production"``. Only merchants in this
            environment are scanned.
        threshold_days: refresh if ``expires_at <= now + threshold_days``.
            Default 10 gives 3 retries at rate(3 days) cadence before expiry.
        dry_run: report which merchants *would* be refreshed without actually
            calling Square. For scheduled tests in production.
        now: injectable timestamp for testing; defaults to ``datetime.now(UTC)``.

    Returns:
        {
            "environment": str,
            "threshold_days": int,
            "dry_run": bool,
            "total_merchants": int,           # merchants scanned
            "refreshed": int,
            "would_refresh": int,             # dry-run only
            "skipped": int,                   # not expiring OR non-OAuth OR revoked
            "failed": int,
            "results": [                      # one entry per merchant scanned
                {"merchant_id": str, "action": str, "expires_at": str|None,
                 "new_expires_at": str|None (on refresh), "error": str (on fail)},
                ...
            ],
        }
    """
    now = now or datetime.now(UTC)
    threshold_seconds = threshold_days * 86_400

    contexts = list_merchant_contexts(status=MERCHANT_STATUS_ACTIVE)
    contexts = [
        c for c in contexts
        if c.environment == environment and c.auth_mode == AUTH_SOURCE_OAUTH
    ]

    results = []
    for context in contexts:
        merchant_id = context.merchant_id
        auth = get_merchant_auth_record(environment, merchant_id)

        if not auth:
            results.append({
                "merchant_id": merchant_id,
                "action": _ACTION_SKIPPED_NO_AUTH,
                "expires_at": None,
            })
            continue

        expires_at = auth.get("expires_at")

        if not auth.get("refresh_token"):
            # No refresh_token means the token will lapse and only a re-OAuth
            # can fix it. Count it as a failure so the Lambda raises and the
            # error alarm emails while there is still time to reconnect.
            results.append({
                "merchant_id": merchant_id,
                "action": _ACTION_FAILED_NO_REFRESH_TOKEN,
                "expires_at": expires_at,
                "error": "No refresh token stored; the merchant must reconnect through OAuth.",
            })
            continue

        if not _needs_refresh(expires_at, threshold_seconds, now):
            results.append({
                "merchant_id": merchant_id,
                "action": _ACTION_SKIPPED_NOT_EXPIRING,
                "expires_at": expires_at,
            })
            continue

        if dry_run:
            results.append({
                "merchant_id": merchant_id,
                "action": _ACTION_WOULD_REFRESH,
                "expires_at": expires_at,
            })
            continue

        try:
            new_auth = refresh_oauth_merchant_access_token(
                environment,
                merchant_id,
                force=True,
            )
            results.append({
                "merchant_id": merchant_id,
                "action": _ACTION_REFRESHED,
                "expires_at": expires_at,
                "new_expires_at": new_auth.get("expires_at") if new_auth else None,
            })
        except (ValueError, ApiError) as error:
            results.append({
                "merchant_id": merchant_id,
                "action": _ACTION_FAILED,
                "expires_at": expires_at,
                "error": str(error),
            })

    return {
        "environment": environment,
        "threshold_days": threshold_days,
        "dry_run": dry_run,
        "total_merchants": len(contexts),
        "refreshed": sum(1 for r in results if r["action"] == _ACTION_REFRESHED),
        "would_refresh": sum(1 for r in results if r["action"] == _ACTION_WOULD_REFRESH),
        "skipped": sum(1 for r in results if r["action"].startswith("skipped_")),
        "failed": sum(1 for r in results if r["action"].startswith("failed")),
        "results": results,
    }
