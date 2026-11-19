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


@contextmanager
def _store_modes(*, order_processing, merchant):
    with (
        patch.object(recovery, "get_order_processing_store_mode", return_value=order_processing),
        patch.object(recovery, "get_merchant_store_mode", return_value=merchant),
    ):
        yield


def _run_main(argv_tail, *, client, store):
    argv = [
        "recover_missed_orders",
        "--environment", "production",
        "--merchant-id", MERCHANT_ID,
        "--location-id", LOCATION_ID,
        "--since", "2026-11-18T00:00:00Z",
        *argv_tail,
    ]
    printed = []
    with (
        patch.object(recovery.sys, "argv", argv),
        _store_modes(order_processing="dynamodb", merchant="dynamodb"),
        patch.object(recovery, "get_webhook_job_queue_url", return_value="https://sqs/queue-prod"),
        patch.object(recovery, "create_square_client_for_merchant", return_value=client),
        _patched(store) as dispatched,
        patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))),
    ):
        exit_code = recovery.main()
    return exit_code, dispatched, printed


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
    def test_production_refuses_a_sqlite_order_processing_store(self):
        with _store_modes(order_processing="sqlite", merchant="dynamodb"):
            with self.assertRaisesRegex(ValueError, "ORDER_PROCESSING_STORE_MODE"):
                recovery._check_store_mode("production", False)

    def test_production_refuses_a_sqlite_merchant_store(self):
        # Otherwise the Square token comes from the local database, not prod.
        with _store_modes(order_processing="dynamodb", merchant="sqlite"):
            with self.assertRaisesRegex(ValueError, "MERCHANT_STORE_MODE"):
                recovery._check_store_mode("production", False)

    def test_apply_refuses_sqlite_stores_in_sandbox_too(self):
        # --apply always sends to SQS, and the deployed worker reads DynamoDB.
        for order_processing, merchant, expected in (
            ("sqlite", "dynamodb", "ORDER_PROCESSING_STORE_MODE"),
            ("dynamodb", "sqlite", "MERCHANT_STORE_MODE"),
        ):
            with self.subTest(order_processing=order_processing, merchant=merchant):
                with _store_modes(order_processing=order_processing, merchant=merchant):
                    with self.assertRaisesRegex(ValueError, expected):
                        recovery._check_store_mode("sandbox", True)

    def test_dynamodb_stores_pass_and_sandbox_dry_run_allows_sqlite(self):
        with _store_modes(order_processing="dynamodb", merchant="dynamodb"):
            recovery._check_store_mode("production", True)
            recovery._check_store_mode("sandbox", True)
        with _store_modes(order_processing="sqlite", merchant="sqlite"):
            recovery._check_store_mode("sandbox", False)

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
            _store_modes(order_processing="sqlite", merchant="dynamodb"),
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


    # --order-id and the setup printout.
    def test_order_id_queues_only_that_order(self):
        client = FakeSquareClient(
            [[_order("other-1", "COMPLETED"), _order("target", "OPEN"), _order("other-2", "OPEN")]]
        )
        store = FakeStore()
        exit_code, dispatched, _ = _run_main(
            ["--order-id", "target", "--apply"], client=client, store=store
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual([job["order_id"] for job in dispatched], ["target"])
        self.assertEqual(list(store.rows), ["target"])
        # Still a paid OPEN order, so it still gets the hold.
        self.assertEqual(dispatched[0]["hold_seconds"], PAID_ORDER_HOLD_SECONDS)

    def test_order_id_still_goes_through_every_check(self):
        client = FakeSquareClient(
            [[_order("unpaid", "OPEN", tenders=False), _order("done", "COMPLETED")]]
        )
        store = FakeStore({"done": "applied"})
        for order_id in ("unpaid", "done"):
            with self.subTest(order_id=order_id):
                _, dispatched, _ = _run_main(
                    ["--order-id", order_id, "--apply"], client=client, store=store
                )
                self.assertEqual(dispatched, [])

    def test_order_id_not_in_window_exits_nonzero(self):
        client = FakeSquareClient([[_order("other", "COMPLETED")]])
        exit_code, dispatched, printed = _run_main(
            ["--order-id", "missing", "--apply"], client=client, store=FakeStore()
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(dispatched, [])
        self.assertTrue(any("not found" in line for line in printed))

    def test_every_run_prints_the_queue_url_store_modes_and_environment(self):
        client = FakeSquareClient([[]])
        _, _, printed = _run_main([], client=client, store=FakeStore())
        setup = "\n".join(printed)

        self.assertIn("https://sqs/queue-prod", setup)
        self.assertIn("order processing store: dynamodb", setup)
        self.assertIn("merchant store:         dynamodb", setup)
        self.assertIn("environment:            production", setup)
        self.assertIn("dry run", setup)


if __name__ == "__main__":
    unittest.main()
