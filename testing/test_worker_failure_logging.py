"""The worker logs one structured JSON line per blocked/failed order or job error.

The outcome tests run the real worker path (real SQLite stores, a fake Square
client) from test_worker_end_to_end, so each line is produced by the code that
runs in the Lambda, not by a hand-built result.

Every test also captures ALL log output (every logger, at DEBUG, plus stdout and
stderr) and fails if a planted secret or customer detail shows up in it. The
secrets are planted where they could plausibly leak from: the merchant's stored
access token, Square error headers and bodies, and exception messages.
"""

import contextlib
import io
import json
import logging
import unittest
from unittest.mock import patch

from square.core.api_error import ApiError

from app.lambda_sqs_worker import lambda_handler
from app.order_processing_store import get_order_processing_state
from app.webhook_worker import RetryableWebhookJobError, process_webhook_job
from app.worker_log import redact_text
from testing.test_worker_end_to_end import (
    ENVIRONMENT,
    MERCHANT_ID,
    ORDER_ID,
    FakeSquareClient,
    WorkerEndToEndHarness,
    _build_live_square_order,
)

WORKER_LOGGER = "app.worker_log"

FAKE_TOKEN = "EAAAlFakeAccessTokenDoNotLog0123456789"
FAKE_REFRESH_TOKEN = "EAAAlFakeRefreshTokenDoNotLog9876543210"
FAKE_APP_SECRET = "sq0csp-FakeAppSecretDoNotLog_abcdefgh"
CUSTOMER_NAME = "Jane Q Customer"
CUSTOMER_EMAIL = "jane.customer@example.com"
CUSTOMER_PHONE = "(415) 555-0142"
PRICE = "$6.75"

FORBIDDEN_STRINGS = [
    FAKE_TOKEN,
    FAKE_REFRESH_TOKEN,
    FAKE_APP_SECRET,
    CUSTOMER_NAME,
    CUSTOMER_EMAIL,
    CUSTOMER_PHONE,
    PRICE,
    "675",
]

# What a careless log line would carry: the request's auth header echoed back,
# and a body with the token and the order's customer and money fields.
LEAKY_HEADERS = {
    "authorization": f"Bearer {FAKE_TOKEN}",
    "x-debug-refresh-token": FAKE_REFRESH_TOKEN,
}


def _square_error(*, category, code, detail, field=None, status_code=400):
    return ApiError(
        status_code=status_code,
        headers=LEAKY_HEADERS,
        body={
            "errors": [
                {"category": category, "code": code, "detail": detail, "field": field}
            ],
            "access_token": FAKE_TOKEN,
            "client_secret": FAKE_APP_SECRET,
            "customer": {
                "given_name": CUSTOMER_NAME,
                "email_address": CUSTOMER_EMAIL,
                "phone_number": CUSTOMER_PHONE,
            },
            "total_money": {"amount": 675, "currency": "USD"},
        },
    )


class _CaptureEverything(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


@contextlib.contextmanager
def capture_all_output():
    """Everything any logger emits at any level, plus stdout and stderr."""
    handler = _CaptureEverything()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    stdout, stderr = io.StringIO(), io.StringIO()
    captured = {"lines": handler.lines}
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            yield captured
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
        captured["text"] = "\n".join(handler.lines) + stdout.getvalue() + stderr.getvalue()


def worker_lines(captured):
    """The worker's own lines, parsed. Each must be exactly one JSON object."""
    prefix = f" {WORKER_LOGGER} "
    events = []
    for line in captured["lines"]:
        if prefix not in line:
            continue
        payload = line.split(prefix, 1)[1]
        assert "\n" not in payload, payload
        events.append(json.loads(payload))
    return events


class WorkerFailureLoggingTests(WorkerEndToEndHarness):
    access_token = FAKE_TOKEN

    def assertNothingSecretLogged(self, captured):
        for forbidden in FORBIDDEN_STRINGS:
            self.assertNotIn(forbidden, captured["text"], f"{forbidden!r} was logged")

    def assertOneEvent(self, captured, **expected):
        events = worker_lines(captured)
        self.assertEqual(len(events), 1, events)
        event = events[0]
        self.assertEqual(
            list(event),
            [
                "event",
                "order_id",
                "merchant_id",
                "environment",
                "processing_state",
                "reason_code",
                "details",
            ],
        )
        for key, value in expected.items():
            self.assertEqual(event[key], value, key)
        return event

    def _order(self, **kwargs):
        order = _build_live_square_order(self.canonical_order, **kwargs)
        # Customer details and money ride on the order and its line items.
        order.customer_id = CUSTOMER_EMAIL
        order.total_money = {"amount": 675, "currency": "USD"}
        for line_item in order.line_items:
            line_item.name = f"{CUSTOMER_NAME} {CUSTOMER_EMAIL} {CUSTOMER_PHONE} {PRICE}"
            line_item.base_price_money = {"amount": 675, "currency": "USD"}
        return order

    def _run(self, client):
        with capture_all_output() as captured:
            processing_state, _ = self._run_worker(client)
        self.assertNothingSecretLogged(captured)
        return processing_state, captured

    # -- blocked -------------------------------------------------------------

    def test_writes_disabled_logs_one_order_blocked_line(self):
        self._connect_merchant(writes_enabled=False)
        self._ingest_order_event()

        processing_state, captured = self._run(FakeSquareClient(self._order()))

        self.assertEqual(processing_state, "blocked")
        event = self.assertOneEvent(
            captured,
            event="order_blocked",
            order_id=ORDER_ID,
            merchant_id=MERCHANT_ID,
            environment=ENVIRONMENT,
            processing_state="blocked",
            reason_code="write_blocked",
        )
        self.assertEqual(
            event["details"],
            {
                "write_blockers": ["writes_disabled_by_operator"],
                "error": "Inventory writes are disabled pending owner approval.",
            },
        )

    def test_missing_binding_logs_the_write_blocker(self):
        self._connect_merchant(approve_binding=False)
        self._ingest_order_event()

        _, captured = self._run(FakeSquareClient(self._order()))

        event = self.assertOneEvent(
            captured, event="order_blocked", reason_code="write_blocked"
        )
        self.assertEqual(event["details"]["write_blockers"], ["missing_approved_binding"])

    def test_unmapped_item_logs_one_order_blocked_line_with_the_variation_ids(self):
        self._connect_merchant()
        self._ingest_order_event()

        processing_state, captured = self._run(
            FakeSquareClient(self._order(sold_prefix="LIVE-UNBOUND-"))
        )

        self.assertEqual(processing_state, "blocked")
        event = self.assertOneEvent(
            captured,
            event="order_blocked",
            order_id=ORDER_ID,
            merchant_id=MERCHANT_ID,
            environment=ENVIRONMENT,
            processing_state="blocked",
            reason_code="line_items_skipped",
        )
        details = event["details"]
        expected_ids = [
            f"LIVE-UNBOUND-{line_item['catalog_object_id']}"
            for line_item in self.canonical_order["line_items"]
        ]
        self.assertEqual(details["skipped_variation_ids"], expected_ids)
        self.assertTrue(details["skipped_reasons"])
        for reason in details["skipped_reasons"]:
            self.assertIn("LIVE-UNBOUND-", reason)
        self.assertEqual(
            details["error"],
            "Refusing to apply inventory changes because one or more line items "
            "were skipped during projection.",
        )
        self.assertEqual(
            set(details), {"skipped_variation_ids", "skipped_reasons", "error"}
        )

    # -- failed --------------------------------------------------------------

    def test_square_inventory_error_logs_one_order_failed_line(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(
            self._order(),
            inventory_error=_square_error(
                category="INVALID_REQUEST_ERROR",
                code="INVALID_VALUE",
                detail="Quantity must be positive.",
                field="changes[0].adjustment.quantity",
            ),
        )

        processing_state, captured = self._run(client)

        self.assertEqual(processing_state, "failed")
        event = self.assertOneEvent(
            captured,
            event="order_failed",
            order_id=ORDER_ID,
            merchant_id=MERCHANT_ID,
            environment=ENVIRONMENT,
            processing_state="failed",
            reason_code="square_inventory_error",
        )
        self.assertEqual(
            event["details"],
            {
                "square_errors": [
                    {
                        "category": "INVALID_REQUEST_ERROR",
                        "code": "INVALID_VALUE",
                        "detail": "Quantity must be positive.",
                        "field": "changes[0].adjustment.quantity",
                    }
                ]
            },
        )

    def test_square_error_detail_echoing_the_token_is_redacted(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(
            self._order(),
            inventory_error=_square_error(
                category="AUTHENTICATION_ERROR",
                code="UNAUTHORIZED",
                detail=f"Authorization: Bearer {FAKE_TOKEN} is not valid",
                status_code=401,
            ),
        )

        _, captured = self._run(client)

        event = self.assertOneEvent(captured, event="order_failed")
        error = event["details"]["square_errors"][0]
        self.assertEqual(error["code"], "UNAUTHORIZED")
        self.assertIn("[REDACTED]", error["detail"])

    def test_square_error_fetching_the_order_logs_one_order_failed_line(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(
            self._order(),
            order_error=_square_error(
                category="API_ERROR",
                code="SERVICE_UNAVAILABLE",
                detail="Service unavailable.",
                status_code=503,
            ),
        )

        _, captured = self._run(client)

        event = self.assertOneEvent(
            captured,
            event="order_failed",
            processing_state="failed",
            reason_code="order_skipped",
        )
        self.assertEqual(
            event["details"],
            {
                "skipped_orders": [
                    {
                        "state": None,
                        "square_errors": [
                            {
                                "category": "API_ERROR",
                                "code": "SERVICE_UNAVAILABLE",
                                "detail": "Service unavailable.",
                                "field": None,
                            }
                        ],
                    }
                ]
            },
        )

    # -- job_error -----------------------------------------------------------

    def test_exception_logs_one_job_error_line(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(
            self._order(),
            # Not an ApiError, so nothing catches it: the job raises.
            order_error=RuntimeError(
                f"connection reset; Authorization: Bearer {FAKE_TOKEN}; "
                f"refresh_token={FAKE_REFRESH_TOKEN} client_secret: {FAKE_APP_SECRET} "
                f"customer {CUSTOMER_EMAIL} {CUSTOMER_PHONE}"
            ),
        )

        with capture_all_output() as captured:
            with self.assertRaises(RuntimeError):
                self._run_worker(client)
        self.assertNothingSecretLogged(captured)

        event = self.assertOneEvent(
            captured,
            event="job_error",
            order_id=ORDER_ID,
            merchant_id=MERCHANT_ID,
            environment=ENVIRONMENT,
            processing_state="pending",
            reason_code="unhandled_exception",
        )
        self.assertEqual(get_order_processing_state(ORDER_ID), "pending")
        self.assertEqual(event["details"]["exception_type"], "RuntimeError")
        self.assertTrue(event["details"]["message"].startswith("connection reset;"))

    def test_failed_transition_logs_only_the_job_error(self):
        self._connect_merchant(writes_enabled=False)
        self._ingest_order_event()

        with (
            patch("app.webhook_worker.mark_order_blocked", return_value=False),
            capture_all_output() as captured,
        ):
            with self.assertRaises(RuntimeError):
                self._run_worker(FakeSquareClient(self._order()))

        self.assertOneEvent(
            captured,
            event="job_error",
            processing_state="pending",
            reason_code="unhandled_exception",
        )

    def test_square_api_error_raised_from_the_job_logs_structured_errors(self):
        error = _square_error(
            category="RATE_LIMIT_ERROR", code="RATE_LIMITED", detail="Slow down."
        )
        with (
            patch("app.webhook_worker.claim_order_processing", side_effect=error),
            capture_all_output() as captured,
        ):
            with self.assertRaises(ApiError):
                process_webhook_job(self.job)
        self.assertNothingSecretLogged(captured)

        event = self.assertOneEvent(
            captured, event="job_error", processing_state=None
        )
        self.assertEqual(
            event["details"],
            {
                "exception_type": "ApiError",
                "square_errors": [
                    {
                        "category": "RATE_LIMIT_ERROR",
                        "code": "RATE_LIMITED",
                        "detail": "Slow down.",
                        "field": None,
                    }
                ],
            },
        )

    def test_order_not_ready_logs_one_job_error_line(self):
        with (
            patch("app.webhook_worker.claim_order_processing", return_value=False),
            patch(
                "app.webhook_worker.get_order_processing_state",
                return_value="processing",
            ),
            capture_all_output() as captured,
        ):
            with self.assertRaises(RetryableWebhookJobError):
                process_webhook_job(self.job)
        self.assertNothingSecretLogged(captured)

        self.assertOneEvent(
            captured,
            event="job_error",
            processing_state="processing",
            reason_code="order_not_ready",
        )

    def test_lambda_logs_a_job_that_raises_once(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(self._order(), order_error=RuntimeError("boom"))
        sqs_event = {
            "Records": [{"messageId": "message-1", "body": json.dumps(self.job)}]
        }

        with (
            patch(
                "app.webhook_worker.create_square_client_for_merchant",
                return_value=client,
            ),
            capture_all_output() as captured,
        ):
            response = lambda_handler(sqs_event, None)

        self.assertEqual(
            response, {"batchItemFailures": [{"itemIdentifier": "message-1"}]}
        )
        self.assertOneEvent(
            captured, event="job_error", reason_code="unhandled_exception"
        )

    def test_lambda_logs_an_unreadable_body(self):
        for body in ["not json", "[1, 2]"]:
            with self.subTest(body=body), capture_all_output() as captured:
                response = lambda_handler(
                    {"Records": [{"messageId": "message-1", "body": body}]}, None
                )
            self.assertEqual(
                response, {"batchItemFailures": [{"itemIdentifier": "message-1"}]}
            )
            self.assertOneEvent(
                captured,
                event="job_error",
                order_id=None,
                reason_code="invalid_job_body",
            )

    # -- no line -------------------------------------------------------------

    def test_applied_order_logs_nothing(self):
        self._connect_merchant()
        self._ingest_order_event()

        processing_state, captured = self._run(FakeSquareClient(self._order()))

        self.assertEqual(processing_state, "applied")
        self.assertEqual(worker_lines(captured), [])


class RedactTextTests(unittest.TestCase):
    def test_redacts_credentials_and_contact_details(self):
        text = (
            f"Authorization: Bearer {FAKE_TOKEN} token={FAKE_REFRESH_TOKEN} "
            f"{FAKE_APP_SECRET} {CUSTOMER_EMAIL} {CUSTOMER_PHONE} +1 415-555-0142"
        )
        redacted = redact_text(text)
        for forbidden in [FAKE_TOKEN, FAKE_REFRESH_TOKEN, FAKE_APP_SECRET, CUSTOMER_EMAIL]:
            self.assertNotIn(forbidden, redacted)
        self.assertNotIn("555-0142", redacted)

    def test_keeps_dates_and_square_ids(self):
        text = "occurred_at 2026-11-20T10:15:00Z for order 2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"
        self.assertEqual(redact_text(text), text)

    def test_truncates_long_text(self):
        self.assertEqual(len(redact_text("x" * 1000)), 300)


if __name__ == "__main__":
    unittest.main()
