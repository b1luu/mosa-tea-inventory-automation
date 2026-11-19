"""End-to-end worker tests: ``process_webhook_job`` with nothing mocked but Square.

Every other worker test patches ``process_orders``, so the wiring between the
worker, the order loader, the binding resolver, the inventory plan, the Square
write and the outcome resolution is never exercised together. These tests run
that whole path against real SQLite stores in a temp directory and a fake
Square client that serves one order and records inventory writes.

The only patch inside ``app`` is ``create_square_client_for_merchant``, which
would otherwise build a real SDK client.
"""

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from square.core.api_error import ApiError

from app import (
    merchant_store_db,
    order_processing_db,
    usage_log_db,
    webhook_event_db,
)
from app.merchant_store import upsert_catalog_binding, upsert_manual_merchant
from app.merchant_store_constants import BINDING_STATUS_APPROVED
from app.order_inventory_projection import (
    is_log_only_inventory_key,
    load_inventory_item_map,
)
from app.order_processing_store import (
    get_order_processing_state,
    reserve_order_processing,
)
from app.usage_log_store import list_usage
from app.webhook_event_store import (
    EVENT_STATUS_ENQUEUED,
    EVENT_STATUS_RECEIVED,
    create_webhook_event,
    get_webhook_event,
    set_webhook_event_status,
)
from app.webhook_worker import process_webhook_job
from testing.order_projection_utils import project_order_summary

ENVIRONMENT = "sandbox"
MERCHANT_ID = "MERCHANT-E2E"
LOCATION_ID = "LOCATION-E2E"
ORDER_ID = "ORDER-E2E-1"
EVENT_ID = "EVENT-E2E-1"

FIXTURE_FILE = Path("testing/fixtures/orders/completed_tgy_brewed_tea.json")

# The merchant's live catalog ids differ from the canonical ids in
# data/recipe_map.json, so the binding has to translate both directions.
LIVE_SOLD_PREFIX = "LIVE-SOLD-"
LIVE_MODIFIER_PREFIX = "LIVE-MOD-"
LIVE_INVENTORY_PREFIX = "LIVE-INV-"


def _load_canonical_order():
    return json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))


def _build_binding_mapping(canonical_order):
    sold_variation_aliases = {}
    modifier_aliases = {}
    for line_item in canonical_order["line_items"]:
        canonical_id = line_item["catalog_object_id"]
        sold_variation_aliases[f"{LIVE_SOLD_PREFIX}{canonical_id}"] = canonical_id
        for modifier in line_item["modifiers"]:
            canonical_modifier_id = modifier["catalog_object_id"]
            modifier_aliases[f"{LIVE_MODIFIER_PREFIX}{canonical_modifier_id}"] = (
                canonical_modifier_id
            )

    return {
        "sold_variation_aliases": sold_variation_aliases,
        "modifier_aliases": modifier_aliases,
        "inventory_variation_ids": {
            inventory_key: f"{LIVE_INVENTORY_PREFIX}{inventory_key}"
            for inventory_key in load_inventory_item_map()
            if not is_log_only_inventory_key(inventory_key)
        },
    }


def _build_live_square_order(canonical_order, *, state="COMPLETED", sold_prefix=LIVE_SOLD_PREFIX):
    """The order as Square would return it for this merchant: live ids, SDK-style attributes."""
    return SimpleNamespace(
        id=ORDER_ID,
        location_id=LOCATION_ID,
        state=state,
        created_at="2026-03-26T19:30:00.000Z",
        tenders=None,
        net_amount_due_money=None,
        line_items=[
            SimpleNamespace(
                uid=line_item["uid"],
                name=line_item["name"],
                quantity=line_item["quantity"],
                catalog_object_id=f"{sold_prefix}{line_item['catalog_object_id']}",
                modifiers=[
                    SimpleNamespace(
                        uid=modifier["uid"],
                        name=modifier["name"],
                        quantity=modifier["quantity"],
                        catalog_object_id=(
                            f"{LIVE_MODIFIER_PREFIX}{modifier['catalog_object_id']}"
                        ),
                    )
                    for modifier in line_item["modifiers"]
                ],
            )
            for line_item in canonical_order["line_items"]
        ],
    )


class _FakeInventoryResponse:
    def model_dump(self, mode="json"):
        return {"counts": [], "changes": []}


class FakeSquareClient:
    """Serves one order and records every inventory write."""

    def __init__(self, order, *, order_error=None, inventory_error=None):
        self._order = order
        self._order_error = order_error
        self._inventory_error = inventory_error
        self.order_requests = []
        self.inventory_requests = []
        self.orders = SimpleNamespace(get=self._get_order)
        self.inventory = SimpleNamespace(
            batch_create_changes=self._batch_create_changes
        )

    def _get_order(self, *, order_id):
        self.order_requests.append(order_id)
        if self._order_error is not None:
            raise self._order_error
        return SimpleNamespace(order=self._order)

    def _batch_create_changes(self, **request):
        self.inventory_requests.append(request)
        if self._inventory_error is not None:
            raise self._inventory_error
        return _FakeInventoryResponse()


class IdempotentFakeSquareClient(FakeSquareClient):
    """Square's idempotency rule: a repeated key with the same body returns the
    original result without applying it again; with a different body it fails."""

    def __init__(self, order):
        super().__init__(order)
        self.applied_requests = {}

    def _batch_create_changes(self, **request):
        self.inventory_requests.append(request)
        key = request["idempotency_key"]
        if key in self.applied_requests:
            if self.applied_requests[key] != request:
                raise ApiError(
                    status_code=400,
                    body={"errors": [{"code": "IDEMPOTENCY_KEY_REUSED"}]},
                )
            return _FakeInventoryResponse()
        self.applied_requests[key] = copy.deepcopy(request)
        return _FakeInventoryResponse()


class WorkerEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        temp_path = Path(self.temp_dir.name)

        patches = [
            patch.object(order_processing_db, "DB_FILE", temp_path / "order_processing.db"),
            patch.object(webhook_event_db, "DB_FILE", temp_path / "webhook_events.db"),
            patch.object(merchant_store_db, "DB_FILE", temp_path / "merchant_store.db"),
            patch.object(usage_log_db, "DB_FILE", temp_path / "usage_log.db"),
            patch.dict(
                os.environ,
                {
                    "SQUARE_ENVIRONMENT": ENVIRONMENT,
                    "ORDER_PROCESSING_STORE_MODE": "sqlite",
                    "WEBHOOK_EVENT_STORE_MODE": "sqlite",
                    "MERCHANT_STORE_MODE": "sqlite",
                    "USAGE_LOG_STORE_MODE": "sqlite",
                },
            ),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)

        self.canonical_order = _load_canonical_order()
        self.binding_mapping = _build_binding_mapping(self.canonical_order)
        self.job = {
            "event_id": EVENT_ID,
            "merchant_id": MERCHANT_ID,
            "environment": ENVIRONMENT,
            "event_type": "order.updated",
            "order_id": ORDER_ID,
            "location_id": LOCATION_ID,
        }

    # -- arrangement helpers -------------------------------------------------

    def _connect_merchant(self, *, writes_enabled=True, approve_binding=True):
        upsert_manual_merchant(
            ENVIRONMENT,
            MERCHANT_ID,
            "fake-access-token",
            selected_location_id=LOCATION_ID,
            display_name="End To End Tea",
            writes_enabled=writes_enabled,
        )
        if approve_binding:
            upsert_catalog_binding(
                ENVIRONMENT,
                MERCHANT_ID,
                LOCATION_ID,
                1,
                self.binding_mapping,
                status=BINDING_STATUS_APPROVED,
            )

    def _ingest_order_event(self):
        """Leave the stores as webhook ingress does just before it enqueues the job."""
        self.assertTrue(
            create_webhook_event(
                event_id=EVENT_ID,
                merchant_id=MERCHANT_ID,
                event_type="order.updated",
                order_id=ORDER_ID,
                order_state="COMPLETED",
                location_id=LOCATION_ID,
                status=EVENT_STATUS_RECEIVED,
            )
        )
        self.assertTrue(
            reserve_order_processing(
                ORDER_ID,
                merchant_id=MERCHANT_ID,
                environment=ENVIRONMENT,
                location_id=LOCATION_ID,
            )
        )
        self.assertTrue(set_webhook_event_status(EVENT_ID, EVENT_STATUS_ENQUEUED))

    def _run_worker(self, client):
        with patch(
            "app.webhook_worker.create_square_client_for_merchant",
            return_value=client,
        ) as mock_create_client:
            processing_state = process_webhook_job(self.job)
        return processing_state, mock_create_client

    def _expected_usage_by_inventory_key(self):
        _, combined_usage = project_order_summary(self.canonical_order)
        return {
            usage["inventory_key"]: Decimal(str(usage["total_amount"]))
            for usage in combined_usage
            if Decimal(str(usage["total_amount"])) > 0
        }

    def _event_status(self):
        return get_webhook_event(EVENT_ID)["status"]

    # -- tests ---------------------------------------------------------------

    def test_completed_order_is_deducted_through_the_merchant_binding(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(_build_live_square_order(self.canonical_order))

        processing_state, mock_create_client = self._run_worker(client)

        self.assertEqual(processing_state, "applied")
        self.assertEqual(get_order_processing_state(ORDER_ID), "applied")
        self.assertEqual(self._event_status(), "processed")
        mock_create_client.assert_called_once_with(ENVIRONMENT, MERCHANT_ID)
        self.assertEqual(client.order_requests, [ORDER_ID])

        self.assertEqual(len(client.inventory_requests), 1)
        request = client.inventory_requests[0]
        self.assertTrue(request["idempotency_key"])
        self.assertTrue(request["ignore_unchanged_counts"])

        expected_usage = self._expected_usage_by_inventory_key()
        self.assertIn("tgy", expected_usage)
        expected_catalog_object_ids = {
            f"{LIVE_INVENTORY_PREFIX}{inventory_key}"
            for inventory_key in expected_usage
            if not is_log_only_inventory_key(inventory_key)
        }
        adjustments = [change["adjustment"] for change in request["changes"]]
        self.assertEqual(
            {adjustment["catalog_object_id"] for adjustment in adjustments},
            expected_catalog_object_ids,
        )
        for change, adjustment in zip(request["changes"], adjustments):
            self.assertEqual(change["type"], "ADJUSTMENT")
            self.assertEqual(adjustment["from_state"], "IN_STOCK")
            self.assertEqual(adjustment["to_state"], "WASTE")
            self.assertEqual(adjustment["location_id"], LOCATION_ID)
            self.assertGreater(Decimal(adjustment["quantity"]), 0)

    def test_applied_order_writes_the_usage_log(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(_build_live_square_order(self.canonical_order))

        self._run_worker(client)

        expected_usage = self._expected_usage_by_inventory_key()
        rows = list_usage(
            ENVIRONMENT,
            MERCHANT_ID,
            LOCATION_ID,
            "tgy",
            "2026-03-26T00:00:00.000Z",
            "2026-03-27T00:00:00.000Z",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["order_id"], ORDER_ID)
        self.assertEqual(Decimal(rows[0]["amount"]), expected_usage["tgy"])

    def test_duplicate_delivery_after_apply_does_not_write_again(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(_build_live_square_order(self.canonical_order))

        self._run_worker(client)
        second_state, _ = self._run_worker(client)

        self.assertEqual(second_state, "applied")
        self.assertEqual(len(client.inventory_requests), 1)
        self.assertEqual(client.order_requests, [ORDER_ID])

    def test_line_item_missing_from_the_binding_blocks_without_writing(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(
            _build_live_square_order(self.canonical_order, sold_prefix="LIVE-UNBOUND-")
        )

        processing_state, _ = self._run_worker(client)

        self.assertEqual(processing_state, "blocked")
        self.assertEqual(get_order_processing_state(ORDER_ID), "blocked")
        self.assertEqual(self._event_status(), "processed")
        self.assertEqual(client.inventory_requests, [])

    def test_writes_disabled_blocks_without_writing(self):
        self._connect_merchant(writes_enabled=False)
        self._ingest_order_event()
        client = FakeSquareClient(_build_live_square_order(self.canonical_order))

        processing_state, _ = self._run_worker(client)

        self.assertEqual(processing_state, "blocked")
        self.assertEqual(get_order_processing_state(ORDER_ID), "blocked")
        self.assertEqual(client.inventory_requests, [])

    def test_missing_approved_binding_blocks_before_square_is_called(self):
        self._connect_merchant(approve_binding=False)
        self._ingest_order_event()
        client = FakeSquareClient(_build_live_square_order(self.canonical_order))

        processing_state, mock_create_client = self._run_worker(client)

        self.assertEqual(processing_state, "blocked")
        mock_create_client.assert_not_called()
        self.assertEqual(client.order_requests, [])
        self.assertEqual(client.inventory_requests, [])

    def test_order_cancelled_during_the_hold_is_cancelled_before_apply(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(
            _build_live_square_order(self.canonical_order, state="CANCELED")
        )

        processing_state, _ = self._run_worker(client)

        self.assertEqual(processing_state, "cancelled_before_apply")
        self.assertEqual(get_order_processing_state(ORDER_ID), "cancelled_before_apply")
        self.assertEqual(self._event_status(), "processed")
        self.assertEqual(client.inventory_requests, [])

    # The next two pin CURRENT behaviour, not desired behaviour: a transient
    # Square error ends as a terminal `failed` and the job returns normally, so
    # SQS never retries it. When transient errors become retryable these should
    # change to assert that the job raises and the order stays `pending`.

    def test_square_error_fetching_the_order_currently_ends_as_failed(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(
            _build_live_square_order(self.canonical_order),
            order_error=ApiError(status_code=503, body="service unavailable"),
        )

        processing_state, _ = self._run_worker(client)

        self.assertEqual(processing_state, "failed")
        self.assertEqual(get_order_processing_state(ORDER_ID), "failed")
        self.assertEqual(self._event_status(), "failed")
        self.assertEqual(client.inventory_requests, [])

    def test_square_error_writing_inventory_currently_ends_as_failed(self):
        self._connect_merchant()
        self._ingest_order_event()
        client = FakeSquareClient(
            _build_live_square_order(self.canonical_order),
            inventory_error=ApiError(status_code=429, body="rate limited"),
        )

        processing_state, _ = self._run_worker(client)

        self.assertEqual(processing_state, "failed")
        self.assertEqual(get_order_processing_state(ORDER_ID), "failed")
        self.assertEqual(self._event_status(), "failed")
        self.assertEqual(len(client.inventory_requests), 1)
        rows = list_usage(
            ENVIRONMENT,
            MERCHANT_ID,
            LOCATION_ID,
            "tgy",
            "2026-03-26T00:00:00.000Z",
            "2026-03-27T00:00:00.000Z",
        )
        self.assertEqual(rows, [])

    # -- retry after a successful Square write --------------------------------

    def _retry_after_write(self, *, minutes_after_creation):
        """First attempt writes to Square, then the usage log raises; SQS retries."""
        self._connect_merchant()
        self._ingest_order_event()
        order = _build_live_square_order(self.canonical_order)
        created = datetime.fromisoformat(order.created_at.replace("Z", "+00:00"))
        client = IdempotentFakeSquareClient(order)
        clock = [created + timedelta(minutes=minutes_after_creation)]

        def _now():
            clock[0] += timedelta(minutes=2)  # time passes between attempts
            return clock[0]

        with (
            patch("app.order_processor._utcnow", side_effect=_now),
            patch("app.inventory_plan.datetime") as plan_datetime,
            patch(
                "app.webhook_worker.record_order_usage",
                side_effect=[RuntimeError("usage log unavailable"), None],
            ),
        ):
            plan_datetime.now.side_effect = lambda tz=None: _now()
            with self.assertRaises(RuntimeError):
                self._run_worker(client)
            self.assertEqual(get_order_processing_state(ORDER_ID), "pending")
            retry_state, _ = self._run_worker(client)
        return retry_state, client

    def test_retry_after_a_successful_write_ends_applied_with_one_deduction(self):
        retry_state, client = self._retry_after_write(minutes_after_creation=10)

        self.assertEqual(retry_state, "applied")
        self.assertEqual(get_order_processing_state(ORDER_ID), "applied")
        self.assertEqual(len(client.inventory_requests), 2)
        self.assertEqual(client.inventory_requests[0], client.inventory_requests[1])
        self.assertEqual(len(client.applied_requests), 1)
        adjustment = client.inventory_requests[0]["changes"][0]["adjustment"]
        self.assertEqual(adjustment["occurred_at"], "2026-03-26T19:30:00.000Z")

    def test_orders_older_than_the_window_still_end_failed_on_that_retry(self):
        # Known limit: Square rejects occurred_at older than 24 hours, so these
        # orders use the current time and the retry is a different request.
        retry_state, client = self._retry_after_write(minutes_after_creation=24 * 60)

        self.assertEqual(retry_state, "failed")
        self.assertEqual(len(client.applied_requests), 1)
        self.assertNotEqual(client.inventory_requests[0], client.inventory_requests[1])


if __name__ == "__main__":
    unittest.main()
