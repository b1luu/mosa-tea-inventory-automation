"""Daily 3 am check: binding coverage plus order reconciliation, one email.

Coverage asks "can every live item be deducted?". Reconciliation asks "was
every sale yesterday actually deducted?". Either finding sends one combined
email; a clean day sends nothing. Every Monday a weekly summary also goes out,
clean or not, so silence never means the check stopped running. See
docs/daily-order-reconciliation-design.md.
"""

import json
import logging
from datetime import timedelta

from app.binding_coverage_report import build_binding_coverage_report
from app.config import get_alarm_notification_topic_arn, get_aws_region
from app.json_utils import to_jsonable
from app.merchant_store import list_merchant_contexts
from app.merchant_store_constants import MERCHANT_STATUS_ACTIVE
from app.order_reconciliation import (
    format_day_lines,
    format_totals_line,
    format_weekly_lines,
    needs_alert as reconciliation_needs_alert,
    problem_count,
    run_daily_reconciliation,
    run_weekly_summary,
    weekly_problem_count,
)
from app.shop_time import shop_today

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
    modifiers = report.get("modifiers") or {}
    return {
        **_build_merchant_summary(merchant_context),
        "blocking_issue_count": int(summary.get("blocking_issue_count") or 0),
        "warning_count": int(summary.get("warning_count") or 0),
        "unmapped_live_variation_count": len(
            sold_variations.get("unmapped_live_variations") or []
        ),
        "unmapped_live_modifier_count": len(modifiers.get("unmapped_live_modifiers") or []),
        "unmapped_names": [
            entry.get("item_name") or entry.get("name") or entry.get("id")
            for entry in (sold_variations.get("unmapped_live_variations") or [])
            + (modifiers.get("unmapped_live_modifiers") or [])
        ],
        "ready_for_approval": bool(summary.get("ready_for_approval")),
    }


def _build_error_summary(merchant_context, error, stage="binding_coverage"):
    return {
        **_build_merchant_summary(merchant_context),
        "stage": stage,
        "error_type": error.__class__.__name__,
        "error": str(error),
    }


def _report_needs_alert(report):
    summary = report.get("summary") or {}
    sold_variations = report.get("sold_variations") or {}
    modifiers = report.get("modifiers") or {}
    # An unmapped modifier is skipped at deduction time, so any that remain after
    # the binding's ignore list are a silent inventory gap worth an alert.
    return (
        int(summary.get("blocking_issue_count") or 0) > 0
        or bool(sold_variations.get("unmapped_live_variations"))
        or bool(modifiers.get("unmapped_live_modifiers"))
    )


def _merchant_name(merchant_context):
    return merchant_context.display_name or merchant_context.merchant_id


def _day_label(day):
    return day.strftime("%a %b ") + str(day.day)


def _format_alert_message(
    checked_merchant_count,
    issue_summaries,
    error_summaries,
    *,
    reconciliations=(),
    report_day=None,
):
    lines = []

    for merchant_context, report in reconciliations:
        if not reconciliation_needs_alert(report):
            continue
        lines.append(
            f"Orders not deducted on {_day_label(report_day)} (Pacific), "
            f"{_merchant_name(merchant_context)}:"
        )
        lines.extend(format_day_lines(report))
        lines.extend(["", format_totals_line(report), ""])
        lines.append(
            "These are not replayed automatically. Replaying an order from before a "
            "physical recount counts it twice. See docs/ops-runbook.md, \"Daily check\"."
        )
        lines.append("")

    if issue_summaries:
        lines.append("Binding coverage issues:")
        for issue in issue_summaries:
            merchant_name = issue["display_name"] or issue["merchant_id"]
            lines.append(
                "- "
                f"{issue['environment']} {merchant_name} "
                f"(merchant_id={issue['merchant_id']}, location_id={issue['location_id']}) "
                f"blocking_issue_count={issue['blocking_issue_count']} "
                f"unmapped_live_variation_count={issue['unmapped_live_variation_count']} "
                f"unmapped_live_modifier_count={issue['unmapped_live_modifier_count']}"
            )
            if issue["unmapped_names"]:
                lines.append(f"  unmapped: {', '.join(issue['unmapped_names'])}")
        lines.append("")

    if error_summaries:
        lines.append("Check errors:")
        for error_summary in error_summaries:
            merchant_name = error_summary["display_name"] or error_summary["merchant_id"]
            lines.append(
                "- "
                f"{error_summary['environment']} {merchant_name} "
                f"[{error_summary['stage']}] "
                f"(merchant_id={error_summary['merchant_id']}, location_id={error_summary['location_id']}) "
                f"{error_summary['error_type']}: {error_summary['error']}"
            )
        lines.append("")

    lines.append(f"checked_merchants={checked_merchant_count}")
    return "\n".join(lines)


def _format_subject(issue_summaries, error_summaries, reconciliations, report_day):
    parts = []
    not_deducted = sum(problem_count(report) for _, report in reconciliations)
    if not_deducted:
        parts.append(f"{not_deducted} order{'s' if not_deducted != 1 else ''} not deducted")
    if any(report["patterns"] for _, report in reconciliations):
        parts.append("paid orders not deductible")
    if issue_summaries:
        parts.append("coverage issues")
    if error_summaries:
        parts.append(f"{len(error_summaries)} check error{'s' if len(error_summaries) != 1 else ''}")
    label = report_day.strftime("%b ") + str(report_day.day) if report_day else "today"
    return f"Mosa Tea daily check ({label}): {', '.join(parts) or 'see details'}"


def _publish(topic_arn, subject, message):
    if not topic_arn:
        raise ValueError(
            "ALARM_NOTIFICATION_TOPIC_ARN must be set before binding coverage findings "
            "can publish an SNS summary."
        )
    _create_sns_client().publish(TopicArn=topic_arn, Subject=subject[:100], Message=message)


def _publish_summary_notification(
    topic_arn,
    checked_merchant_count,
    issue_summaries,
    error_summaries,
    *,
    reconciliations=(),
    report_day=None,
):
    _publish(
        topic_arn,
        _format_subject(issue_summaries, error_summaries, reconciliations, report_day),
        _format_alert_message(
            checked_merchant_count,
            issue_summaries,
            error_summaries,
            reconciliations=reconciliations,
            report_day=report_day,
        ),
    )


def _publish_weekly_summary(topic_arn, weekly_reports, last_day):
    first_day = last_day - timedelta(days=6)
    problems = sum(weekly_problem_count(reports) for _, reports in weekly_reports)
    span = f"{first_day.strftime('%b')} {first_day.day} to {last_day.strftime('%b')} {last_day.day}"
    status = (
        "all clean"
        if problems == 0
        else f"{problems} order{'s' if problems != 1 else ''} not deducted (already emailed)"
    )
    lines = [f"Weekly check, {span} (Pacific).", ""]
    for merchant_context, reports in weekly_reports:
        lines.append(f"{_merchant_name(merchant_context)}:")
        lines.extend(format_weekly_lines(reports))
        lines.append("")
    lines.append(
        "Sent every Monday, clean or not. If this email stops arriving, the daily "
        "check has stopped running."
    )
    _publish(topic_arn, f"Mosa Tea weekly check ({span}): {status}", "\n".join(lines))


def _reconciliation_log_payload(merchant_context, report):
    return {
        "merchant_id": merchant_context.merchant_id,
        "day": report["day"],
        "totals": report["totals"],
        "patterns": report["patterns"],
        "problem_order_ids": {
            name: [entry["order_id"] for entry in report["buckets"][name]]
            for name in ("blocked", "failed", "stuck", "missed", "reversed")
            if report["buckets"][name]
        },
    }


def lambda_handler(event, context):
    today = shop_today()
    report_day = today - timedelta(days=1)
    merchant_contexts = list_merchant_contexts(status=MERCHANT_STATUS_ACTIVE)
    checked_merchant_count = len(merchant_contexts)
    issue_summaries = []
    error_summaries = []
    reconciliations = []
    weekly_reports = []

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
        else:
            logger.info(
                "binding_coverage_report | payload=%s",
                json.dumps(to_jsonable(report), sort_keys=True),
            )
            if _report_needs_alert(report):
                issue_summaries.append(_build_issue_summary(merchant_context, report))

        try:
            reconciliation = run_daily_reconciliation(merchant_context, report_day)
        except Exception as error:
            error_summary = _build_error_summary(merchant_context, error, stage="order_reconciliation")
            error_summaries.append(error_summary)
            logger.exception(
                "order_reconciliation_error | payload=%s",
                json.dumps(to_jsonable(error_summary), sort_keys=True),
            )
        else:
            reconciliations.append((merchant_context, reconciliation))
            logger.info(
                "order_reconciliation | payload=%s",
                json.dumps(
                    to_jsonable(_reconciliation_log_payload(merchant_context, reconciliation)),
                    sort_keys=True,
                ),
            )

        if today.weekday() == 0:
            try:
                weekly_reports.append(
                    (merchant_context, run_weekly_summary(merchant_context, report_day))
                )
            except Exception as error:
                error_summary = _build_error_summary(merchant_context, error, stage="weekly_summary")
                error_summaries.append(error_summary)
                logger.exception(
                    "weekly_summary_error | payload=%s",
                    json.dumps(to_jsonable(error_summary), sort_keys=True),
                )

    topic_arn = get_alarm_notification_topic_arn()
    weekly_summary_sent = False
    if weekly_reports:
        _publish_weekly_summary(topic_arn, weekly_reports, report_day)
        weekly_summary_sent = True

    reconciliation_results = [
        _reconciliation_log_payload(merchant_context, report)
        for merchant_context, report in reconciliations
    ]
    needs_daily_email = (
        bool(issue_summaries)
        or bool(error_summaries)
        or any(reconciliation_needs_alert(report) for _, report in reconciliations)
    )

    if needs_daily_email:
        _publish_summary_notification(
            topic_arn,
            checked_merchant_count,
            issue_summaries,
            error_summaries,
            reconciliations=reconciliations,
            report_day=report_day,
        )
        result = {
            "checked_merchant_count": checked_merchant_count,
            "issue_merchant_count": len(issue_summaries),
            "error_merchant_count": len(error_summaries),
            "published_alert": True,
            "issues": issue_summaries,
            "errors": error_summaries,
            "reconciliation": reconciliation_results,
            "weekly_summary_sent": weekly_summary_sent,
        }
        logger.warning(
            "daily_check_alert_published | payload=%s",
            json.dumps(to_jsonable(result), sort_keys=True),
        )
        return result

    result = {
        "checked_merchant_count": checked_merchant_count,
        "issue_merchant_count": 0,
        "error_merchant_count": 0,
        "published_alert": False,
        "reconciliation": reconciliation_results,
        "weekly_summary_sent": weekly_summary_sent,
    }
    logger.info(
        "daily_check_clean | payload=%s",
        json.dumps(to_jsonable(result), sort_keys=True),
    )
    return result
