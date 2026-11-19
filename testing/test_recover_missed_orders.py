import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from scripts import recover_missed_orders as recovery
from app.order_commit_rules import PAID_ORDER_HOLD_SECONDS

MERCHANT_ID = "MERCHANT-1"
LOCATION_ID = "LOCATION-1"


def _order(order_id, state, *, tenders=True, due=0, location_id=LOCATION_ID):
    return SimpleNamespace(
        id=order_id,
        state=state,
        tenders=[{"id": "t"}] if tenders else [],
        net_amount_due_money=SimpleNamespace(amount=due),
        location_id=location_id,
        created_at="2026-11-18T20:00:00Z",
    )


class FakeStore:
    """In-memory order_processing store with the real reserve/clear semantics."""

    def __init__(self, states=None):
        self.rows = {order_id: {"processing_state": s} for order_id, s in (states or {}).items()}
        self.cleared = []

    def get_order_processing_state(self, order_id):
        row = self.rows.get(order_id)
        return row["processing_state"] if row else None

    def reserve_order_processing(self, order_id, *, merchant_id=None, environment=None, location_id=None):
        if order_id in self.rows:
            return False
        self.rows[order_id] = {
            "processing_state": "pending",
            "merchant_id": merchant_id,
            "environment": environment,
            "location_id": location_id,
        }
        return True

    def clear_order_processing_reservation(self, order_id):
        row = self.rows.get(order_id)
        if row and row["processing_state"] == "pending":
            del self.rows[order_id]
            self.cleared.append(order_id)
            return True
        return False


class FakeSquareClient:
    def __init__(self, pages):
        self._pages = pages
        self.calls = []
        self.orders = self

    def search(self, **kwargs):
        self.calls.append(kwargs)
        index = int(kwargs.get("cursor") or 0)
        next_cursor = str(index + 1) if index + 1 < len(self._pages) else None
        return SimpleNamespace(orders=self._pages[index], cursor=next_cursor)


@contextmanager
def _patched(store, dispatch=None):
    dispatched = []

    def _record(job):
        dispatched.append(job)

    with (
        patch.object(recovery, "get_order_processing_state", store.get_order_processing_state),
        patch.object(recovery, "reserve_order_processing", store.reserve_order_processing),
        patch.object(
            recovery, "clear_order_processing_reservation", store.clear_order_processing_reservation
        ),
        patch.object(recovery, "dispatch_webhook_job_to_sqs", dispatch or _record),
    ):
        yield dispatched


def _recover(orders, *, apply_changes=True, environment="production"):
    lines = []
    summary = recovery.recover(
        orders,
        merchant_id=MERCHANT_ID,
        environment=environment,
        default_location_id=LOCATION_ID,
        apply_changes=apply_changes,
        out=lines.append,
    )
    return summary, lines


class RecoverMissedOrdersTests(unittest.TestCase):
    # 1. Kiosk / paid-but-OPEN orders.
    def test_paid_open_order_without_a_row_is_queued(self):
        store = FakeStore()
        with _patched(store) as dispatched:
            summary, _ = _recover([_order("kiosk-1", "OPEN")])

        self.assertEqual(summary["queued"], 1)
        self.assertEqual([job["order_id"] for job in dispatched], ["kiosk-1"])

    def test_unpaid_open_and_cancelled_orders_are_not_queued(self):
        store = FakeStore()
        orders = [
            _order("unpaid", "OPEN", tenders=False),
            _order("owes-money", "OPEN", due=450),
            _order("cancelled", "CANCELED"),
        ]
        with _patched(store) as dispatched:
            summary, _ = _recover(orders)

        self.assertEqual(dispatched, [])
        self.assertEqual(store.rows, {})
        self.assertEqual(summary["committable"], 0)

    def test_search_covers_every_state_by_created_at(self):
        client = FakeSquareClient([[_order("a", "COMPLETED")], [_order("b", "OPEN")]])
        orders = recovery._search_orders_created_since(client, LOCATION_ID, "2026-11-18T00:00:00Z")

        self.assertEqual([o.id for o in orders], ["a", "b"])
        query_filter = client.calls[0]["query"]["filter"]
        self.assertNotIn("state_filter", query_filter)
        self.assertEqual(
            query_filter["date_time_filter"], {"created_at": {"start_at": "2026-11-18T00:00:00Z"}}
        )

    # 2. Store mode.
    def test_production_refuses_the_sqlite_store(self):
        with patch.object(recovery, "get_order_processing_store_mode", return_value="sqlite"):
            with self.assertRaises(ValueError):
                recovery._check_store_mode("production")

    def test_production_allows_the_dynamodb_store_and_sandbox_allows_sqlite(self):
        with patch.object(recovery, "get_order_processing_store_mode", return_value="dynamodb"):
            recovery._check_store_mode("production")
        with patch.object(recovery, "get_order_processing_store_mode", return_value="sqlite"):
            recovery._check_store_mode("sandbox")

    def test_main_exits_before_calling_square_when_store_mode_is_wrong(self):
        argv = [
            "recover_missed_orders",
            "--environment", "production",
            "--merchant-id", MERCHANT_ID,
            "--location-id", LOCATION_ID,
            "--since", "2026-11-18T00:00:00Z",
        ]
        with (
            patch.object(recovery.sys, "argv", argv),
            patch.object(recovery, "get_order_processing_store_mode", return_value="sqlite"),
            patch.object(
                recovery,
                "create_square_client_for_merchant",
                side_effect=AssertionError("must not reach Square"),
            ) as mock_client,
            patch("builtins.print"),
        ):
            self.assertEqual(recovery.main(), 1)
        mock_client.assert_not_called()

    # 3. Rows that already exist, and dispatch failure.
    def test_existing_rows_are_never_requeued(self):
        store = FakeStore(
            {"applied": "applied", "blocked": "blocked", "failed": "failed", "held": "pending"}
        )
        orders = [_order(order_id, "COMPLETED") for order_id in store.rows]
        with _patched(store) as dispatched:
            summary, lines = _recover(orders)

        self.assertEqual(dispatched, [])
        self.assertEqual(summary["pending"], 1)
        self.assertTrue(any("already pending" in line and "held" in line for line in lines))

    def test_dispatch_failure_clears_the_reservation(self):
        store = FakeStore()

        def _boom(job):
            raise RuntimeError("sqs down")

        with _patched(store, dispatch=_boom):
            summary, _ = _recover([_order("o-1", "COMPLETED"), _order("o-2", "COMPLETED")])

        self.assertEqual(store.rows, {})
        self.assertEqual(store.cleared, ["o-1", "o-2"])
        self.assertEqual(summary["dispatch_failed"], 2)
        self.assertEqual(summary["queued"], 0)

    def test_dry_run_writes_nothing(self):
        store = FakeStore()
        with _patched(store) as dispatched:
            summary, lines = _recover([_order("o-1", "COMPLETED")], apply_changes=False)

        self.assertEqual(store.rows, {})
        self.assertEqual(dispatched, [])
        self.assertEqual(summary["missed"], 1)
        self.assertTrue(any(line.startswith("would queue") for line in lines))

    # 4. Hold.
    def test_paid_open_orders_get_the_paid_order_hold(self):
        store = FakeStore()
        with _patched(store) as dispatched:
            _recover([_order("kiosk-1", "OPEN"), _order("done-1", "COMPLETED")])

        jobs = {job["order_id"]: job for job in dispatched}
        self.assertEqual(jobs["kiosk-1"]["hold_seconds"], PAID_ORDER_HOLD_SECONDS)
        self.assertNotIn("hold_seconds", jobs["done-1"])

    # 5. Merchant context on the job and the row.
    def test_job_and_row_carry_merchant_environment_and_location(self):
        store = FakeStore()
        orders = [_order("o-1", "COMPLETED"), _order("o-2", "COMPLETED", location_id=None)]
        with _patched(store) as dispatched:
            _recover(orders)

        for job in dispatched:
            self.assertEqual(job["merchant_id"], MERCHANT_ID)
            self.assertEqual(job["environment"], "production")
            self.assertEqual(job["location_id"], LOCATION_ID)
            row = store.rows[job["order_id"]]
            self.assertEqual(
                (row["merchant_id"], row["environment"], row["location_id"]),
                (MERCHANT_ID, "production", LOCATION_ID),
            )


if __name__ == "__main__":
    unittest.main()
