"""Scheduled OAuth token refresh: renews tokens well before Square's 30-day expiry.

This is the proactive half of token upkeep. The reactive half already runs on
every order (``resolve_merchant_access_token`` renews a token within five
minutes of expiry). The scheduler renews ten days ahead, so a failure surfaces
through the error alarm while there is still time to reconnect.

Invoke with ``{"dry_run": true}`` to see what would be renewed without calling
Square.
"""

import json
import logging

from app.config import get_square_environment_name
from app.json_utils import to_jsonable
from app.oauth_refresh_scheduler import refresh_expiring_tokens

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class OAuthRefreshFailedError(RuntimeError):
    """Raised so CloudWatch counts the invocation as an error and the alarm fires."""


def lambda_handler(event, context):
    event = event or {}
    summary = refresh_expiring_tokens(
        environment=get_square_environment_name(),
        dry_run=bool(event.get("dry_run", False)),
    )
    payload = json.dumps(to_jsonable(summary), sort_keys=True)

    if summary["failed"]:
        logger.error("oauth_refresh_failed | payload=%s", payload)
        failed_merchants = [
            result["merchant_id"]
            for result in summary["results"]
            if result["action"].startswith("failed")
        ]
        raise OAuthRefreshFailedError(
            f"OAuth refresh failed for {summary['failed']} merchant(s): "
            f"{', '.join(failed_merchants)}. See the oauth_refresh_failed log line."
        )

    logger.info("oauth_refresh_complete | payload=%s", payload)
    return summary
