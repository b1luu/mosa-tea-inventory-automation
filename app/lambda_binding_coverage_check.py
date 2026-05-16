import json
import logging

from app.binding_coverage_report import build_binding_coverage_report
from app.config import get_alarm_notification_topic_arn, get_aws_region
from app.json_utils import to_jsonable
from app.merchant_store import list_merchant_contexts
from app.merchant_store_constants import MERCHANT_STATUS_ACTIVE

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _create_sns_client():
    import boto3

    return boto3.client("sns", region_name=get_aws_region())


def _build_merchant_summary(merchant_context):
    return {
        "environment": merchant_context.environment,
        "merchant_id": merchant_context.merchant_id,
        "display_name": merchant_context.display_name,
        "location_id": merchant_context.location_id,
        "writes_enabled": merchant_context.writes_enabled,
        "binding_version": merchant_context.binding_version,
    }


def _build_issue_summary(merchant_context, report):
    summary = report.get("summary") or {}
    sold_variations = report.get("sold_variations") or {}
    return {
        **_build_merchant_summary(merchant_context),
        "blocking_issue_count": int(summary.get("blocking_issue_count") or 0),
        "warning_count": int(summary.get("warning_count") or 0),
        "unmapped_live_variation_count": len(
            sold_variations.get("unmapped_live_variations") or []
        ),
        "ready_for_approval": bool(summary.get("ready_for_approval")),
    }


def _build_error_summary(merchant_context, error):
    return {
        **_build_merchant_summary(merchant_context),
        "error_type": error.__class__.__name__,
        "error": str(error),
    }


def _report_needs_alert(report):
    summary = report.get("summary") or {}
    sold_variations = report.get("sold_variations") or {}
    return (
        int(summary.get("blocking_issue_count") or 0) > 0
        or bool(sold_variations.get("unmapped_live_variations"))
    )


def _format_alert_message(checked_merchant_count, issue_summaries, error_summaries):
    lines = [
        "Scheduled binding coverage check detected merchant coverage issues.",
        "",
        (
            "summary: "
            f"checked_merchants={checked_merchant_count} "
            f"issue_merchants={len(issue_summaries)} "
            f"error_merchants={len(error_summaries)}"
        ),
    ]

    if issue_summaries:
        lines.extend(["", "affected_merchants:"])
        for issue in issue_summaries:
            merchant_name = issue["display_name"] or issue["merchant_id"]
            lines.append(
                "- "
                f"{issue['environment']} {merchant_name} "
                f"(merchant_id={issue['merchant_id']}, location_id={issue['location_id']}) "
                f"blocking_issue_count={issue['blocking_issue_count']} "
                f"unmapped_live_variation_count={issue['unmapped_live_variation_count']}"
            )

    if error_summaries:
        lines.extend(["", "evaluation_errors:"])
        for error_summary in error_summaries:
            merchant_name = error_summary["display_name"] or error_summary["merchant_id"]
            lines.append(
                "- "
                f"{error_summary['environment']} {merchant_name} "
                f"(merchant_id={error_summary['merchant_id']}, location_id={error_summary['location_id']}) "
                f"{error_summary['error_type']}: {error_summary['error']}"
            )

    return "\n".join(lines)


def _publish_summary_notification(topic_arn, checked_merchant_count, issue_summaries, error_summaries):
    if not topic_arn:
        raise ValueError(
            "ALARM_NOTIFICATION_TOPIC_ARN must be set before binding coverage findings "
            "can publish an SNS summary."
        )

    subject = (
        "Mosa Tea binding coverage check: "
        f"{len(issue_summaries)} issue merchants, {len(error_summaries)} evaluation errors"
    )
    message = _format_alert_message(
        checked_merchant_count,
        issue_summaries,
        error_summaries,
    )
    _create_sns_client().publish(
        TopicArn=topic_arn,
        Subject=subject[:100],
        Message=message,
    )


def lambda_handler(event, context):
    merchant_contexts = list_merchant_contexts(status=MERCHANT_STATUS_ACTIVE)
    checked_merchant_count = len(merchant_contexts)
    issue_summaries = []
    error_summaries = []

    for merchant_context in merchant_contexts:
        if not merchant_context.location_id:
            error = ValueError("Merchant has no selected location configured.")
            error_summary = _build_error_summary(merchant_context, error)
            error_summaries.append(error_summary)
            logger.error(
                "binding_coverage_report_error | payload=%s",
                json.dumps(to_jsonable(error_summary), sort_keys=True),
            )
            continue

        try:
            report = build_binding_coverage_report(
                merchant_context.environment,
                merchant_context.merchant_id,
                merchant_context.location_id,
            )
        except Exception as error:
            error_summary = _build_error_summary(merchant_context, error)
            error_summaries.append(error_summary)
            logger.exception(
                "binding_coverage_report_error | payload=%s",
                json.dumps(to_jsonable(error_summary), sort_keys=True),
            )
            continue

        logger.info(
            "binding_coverage_report | payload=%s",
            json.dumps(to_jsonable(report), sort_keys=True),
        )

        if _report_needs_alert(report):
            issue_summaries.append(_build_issue_summary(merchant_context, report))

    if issue_summaries or error_summaries:
        _publish_summary_notification(
            get_alarm_notification_topic_arn(),
            checked_merchant_count,
            issue_summaries,
            error_summaries,
        )
        result = {
            "checked_merchant_count": checked_merchant_count,
            "issue_merchant_count": len(issue_summaries),
            "error_merchant_count": len(error_summaries),
            "published_alert": True,
            "issues": issue_summaries,
            "errors": error_summaries,
        }
        logger.warning(
            "coverage_alert_published | payload=%s",
            json.dumps(to_jsonable(result), sort_keys=True),
        )
        return result

    result = {
        "checked_merchant_count": checked_merchant_count,
        "issue_merchant_count": 0,
        "error_merchant_count": 0,
        "published_alert": False,
    }
    logger.info(
        "coverage_clean | payload=%s",
        json.dumps(result, sort_keys=True),
    )
    return result
