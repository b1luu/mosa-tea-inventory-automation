"""One structured JSON log line per worker failure, for CloudWatch.

Events:
  order_blocked  an order ended blocked (write blockers, or skipped line items)
  order_failed   an order ended failed (Square error, or the order was skipped)
  job_error      a webhook job raised

Every line has the same top-level fields: event, order_id, merchant_id,
environment, processing_state, reason_code, details.

Only fields named here are copied out of the processing result, so line item
names, prices, totals and customer data never reach the log, whatever the
result carries. Free text (exception messages, Square error details, skip
reasons) is truncated and has anything token-shaped redacted, because an
exception message is the one place a secret could ride along unseen.
"""

import json
import logging
import re

from square.core.api_error import ApiError

from app.order_processing_store import (
    PROCESSING_STATE_BLOCKED,
    PROCESSING_STATE_FAILED,
)
from app.square_errors import square_error_details

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

EVENT_ORDER_BLOCKED = "order_blocked"
EVENT_ORDER_FAILED = "order_failed"
EVENT_JOB_ERROR = "job_error"

MAX_TEXT_LENGTH = 300
MAX_LIST_ITEMS = 10

_REDACTED = "[REDACTED]"
_SECRET_PATTERNS = [
    # Authorization header values, in any form they get stringified.
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(['\"]?authorization['\"]?\s*[:=]\s*)['\"]?[^'\",}\s]+"),
    # Square access/refresh tokens and application secrets.
    re.compile(r"\bEAAA[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsq0[a-z]{3}-[A-Za-z0-9_-]{8,}"),
    # key=value / key: value for anything named like a credential.
    re.compile(
        r"(?i)(['\"]?[a-z_]*(token|secret|password|api_key)['\"]?\s*[:=]\s*)"
        r"['\"]?[^'\",}\s]+"
    ),
    # Customer contact details.
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(
        r"(?<![\w-])\+?(?:1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\w-])"
    ),
]


def redact_text(value):
    if value is None:
        return None
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(
                lambda match: (
                    match.group(1) + _REDACTED
                    if match.group(1)
                    and match.group(1).rstrip().endswith((":", "="))
                    else _REDACTED
                ),
                text,
            )
        else:
            text = pattern.sub(_REDACTED, text)
    if len(text) > MAX_TEXT_LENGTH:
        text = text[: MAX_TEXT_LENGTH - 3] + "..."
    return text


def _first(items):
    return list(items)[:MAX_LIST_ITEMS]


def _dedupe(values):
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _square_errors(errors):
    return [
        {
            "category": error.get("category"),
            "code": error.get("code"),
            "detail": redact_text(error.get("detail")),
            "field": error.get("field"),
        }
        for error in _first(errors or [])
        if isinstance(error, dict)
    ]


def _blocked_reason_and_details(result):
    details = {}
    write_blockers = result.get("blocking_reasons") or []
    skipped_line_items = [
        item for item in result.get("skipped_line_items") or [] if isinstance(item, dict)
    ]
    inventory_response = result.get("inventory_response") or {}

    if write_blockers:
        reason_code = "write_blocked"
        details["write_blockers"] = _first(str(blocker) for blocker in write_blockers)
    elif skipped_line_items:
        reason_code = "line_items_skipped"
    else:
        reason_code = "blocked"

    if skipped_line_items:
        details["skipped_variation_ids"] = _first(
            item.get("sold_variation_id") for item in skipped_line_items
        )
        details["skipped_reasons"] = _first(
            _dedupe(redact_text(item.get("reason")) for item in skipped_line_items)
        )

    # The plan's blocking reason or the write blocker's message. Never the
    # string form of a Square error, which carries headers and the body.
    message = inventory_response.get("error") or inventory_response.get("blocked_reason")
    if message and not inventory_response.get("square_errors"):
        details["error"] = redact_text(message)

    return reason_code, details


def _failed_reason_and_details(result):
    inventory_response = result.get("inventory_response") or {}
    if inventory_response.get("square_errors") or "error" in inventory_response:
        return "square_inventory_error", {
            "square_errors": _square_errors(inventory_response.get("square_errors")),
        }

    skipped_orders = [
        order for order in result.get("skipped_orders") or [] if isinstance(order, dict)
    ]
    if skipped_orders:
        summaries = []
        for order in _first(skipped_orders):
            summary = {"state": order.get("state")}
            if order.get("square_errors") is not None:
                summary["square_errors"] = _square_errors(order.get("square_errors"))
            else:
                summary["reason"] = redact_text(order.get("reason"))
            summaries.append(summary)
        return "order_skipped", {"skipped_orders": summaries}

    return "no_projected_orders", {}


def _emit(level, event):
    logger.log(level, json.dumps(event, default=str))


def _event(event, *, order_id, merchant_id, environment, processing_state, reason_code, details):
    return {
        "event": event,
        "order_id": order_id,
        "merchant_id": merchant_id,
        "environment": environment,
        "processing_state": processing_state,
        "reason_code": reason_code,
        "details": details,
    }


def log_order_outcome(*, order_id, merchant_id, environment, processing_state, result):
    """Log one line if the order ended blocked or failed; nothing otherwise.

    Never raises: the order has already moved to its terminal state, and a
    logging bug must not turn that into a job error and a retry.
    """
    if processing_state == PROCESSING_STATE_BLOCKED:
        event, level, build = EVENT_ORDER_BLOCKED, logging.WARNING, _blocked_reason_and_details
    elif processing_state == PROCESSING_STATE_FAILED:
        event, level, build = EVENT_ORDER_FAILED, logging.ERROR, _failed_reason_and_details
    else:
        return
    try:
        reason_code, details = build(result or {})
    except Exception as error:
        reason_code, details = "log_details_unavailable", {
            "exception_type": type(error).__name__,
        }
    _emit(
        level,
        _event(
            event,
            order_id=order_id,
            merchant_id=merchant_id,
            environment=environment,
            processing_state=processing_state,
            reason_code=reason_code,
            details=details,
        ),
    )


def log_job_error(job, error, *, reason_code, processing_state=None):
    """Log one line for a job that raised. Never raises."""
    job = job if isinstance(job, dict) else {}
    try:
        details = {"exception_type": type(error).__name__}
        if isinstance(error, ApiError):
            details["square_errors"] = _square_errors(square_error_details(error))
        else:
            details["message"] = redact_text(error)
    except Exception:
        details = {"exception_type": "unknown"}
    _emit(
        logging.ERROR,
        _event(
            EVENT_JOB_ERROR,
            order_id=job.get("order_id"),
            merchant_id=job.get("merchant_id"),
            environment=job.get("environment"),
            processing_state=processing_state,
            reason_code=reason_code,
            details=details,
        ),
    )
