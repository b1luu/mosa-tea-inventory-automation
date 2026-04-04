import unittest
from decimal import Decimal
from unittest.mock import patch

from testing.run_live_cloud_canary import (
    _inventory_mismatches,
    _normalize_usage_by_inventory_key,
    _pipeline_has_terminal_failure,
    _pipeline_is_settled,
    _summarize_webhook_events,
    _wait_for_pipeline_settlement,
    _wait_for_square_order_completed,
)


class LiveCloudCanaryTests(unittest.TestCase):
    def test_normalize_usage_by_inventory_key_quantizes_amounts(self):
        normalized = _normalize_usage_by_inventory_key(
            [
                {
                    "inventory_key": "tgy",
                    "total_amount": Decimal("8.000000000000000000000000001"),
                },
                {
                    "inventory_key": "sugar_syrup",
                    "total_amount": Decimal("54.0"),
                },
            ]
        )

        self.assertEqual(normalized["tgy"], Decimal("8.00000"))
        self.assertEqual(normalized["sugar_syrup"], Decimal("54.00000"))

    def test_summarize_webhook_events_counts_statuses(self):
        summary = _summarize_webhook_events(
            [
                {"status": "ignored"},
                {"status": "processed"},
                {"status": "ignored"},
            ]
        )

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["processed_count"], 1)
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(summary["status_counts"]["ignored"], 2)

    def test_pipeline_is_settled_requires_applied_and_single_processed_event(self):
        self.assertTrue(
            _pipeline_is_settled(
                {"processing_state": "applied"},
                {"processed_count": 1, "failed_count": 0},
            )
        )
        self.assertFalse(
            _pipeline_is_settled(
                {"processing_state": "processing"},
                {"processed_count": 1, "failed_count": 0},
            )
        )

    def test_pipeline_has_terminal_failure_detects_failed_or_blocked_states(self):
        self.assertTrue(
            _pipeline_has_terminal_failure(
                {"processing_state": "failed"},
                {"failed_count": 0},
            )
        )
        self.assertTrue(
            _pipeline_has_terminal_failure(
                {"processing_state": "pending"},
                {"failed_count": 1},
            )
        )
        self.assertFalse(
            _pipeline_has_terminal_failure(
                {"processing_state": "applied"},
                {"failed_count": 0},
            )
        )

    def test_inventory_mismatches_returns_empty_when_after_matches_projection(self):
        before = {
            "tgy": {
                "projected_adjustment": {
                    "after": {
                        "in_stock_quantity": Decimal("122.84444"),
                        "waste_quantity": Decimal("0.15556"),
                    }
                }
            }
        }
        after = {
            "tgy": {
                "in_stock_quantity": Decimal("122.84444"),
                "waste_quantity": Decimal("0.15556"),
            }
        }

        self.assertEqual(_inventory_mismatches(before, after), [])

    def test_inventory_mismatches_reports_expected_vs_actual(self):
        before = {
            "tgy": {
                "projected_adjustment": {
                    "after": {
                        "in_stock_quantity": Decimal("122.84444"),
                        "waste_quantity": Decimal("0.15556"),
                    }
                }
            }
        }
        after = {
            "tgy": {
                "in_stock_quantity": Decimal("122.85000"),
                "waste_quantity": Decimal("0.15000"),
            }
        }

        mismatches = _inventory_mismatches(before, after)

        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["inventory_key"], "tgy")

    def test_wait_for_square_order_completed_emits_poll_status(self):
        states = iter(["OPEN", "COMPLETED"])

        client = type(
            "Client",
            (),
            {
                "orders": type(
                    "Orders",
                    (),
                    {
                        "get": staticmethod(
                            lambda order_id: type(
                                "Response",
                                (),
                                {
                                    "order": type(
                                        "Order",
                                        (),
                                        {"id": order_id, "state": next(states)},
                                    )()
                                },
                            )()
                        )
                    },
                )()
            },
        )()
        events = []

        order = _wait_for_square_order_completed(
            client,
            "order-1",
            timeout_seconds=1,
            poll_seconds=0,
            status_callback=lambda message, **fields: events.append((message, fields)),
        )

        self.assertEqual(order.state, "COMPLETED")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "waiting_for_square_order_completion")
        self.assertEqual(events[0][1]["current_state"], "OPEN")

    def test_wait_for_pipeline_settlement_emits_poll_status(self):
        order_rows = iter(
            [
                {"processing_state": "pending"},
                {"processing_state": "applied"},
            ]
        )
        event_lists = iter(
            [
                [{"status": "enqueued"}],
                [{"status": "processed"}],
            ]
        )
        events = []

        with (
            patch(
                "testing.run_live_cloud_canary._get_order_processing_row",
                side_effect=lambda order_id: next(order_rows),
            ),
            patch(
                "testing.run_live_cloud_canary._list_webhook_events_for_order",
                side_effect=lambda order_id: next(event_lists),
            ),
        ):
            snapshot = _wait_for_pipeline_settlement(
                "order-1",
                timeout_seconds=1,
                poll_seconds=0,
                status_callback=lambda message, **fields: events.append(
                    (message, fields)
                ),
            )

        self.assertEqual(
            snapshot["order_processing"]["processing_state"],
            "applied",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "waiting_for_aws_pipeline")
        self.assertEqual(events[0][1]["processing_state"], "pending")


if __name__ == "__main__":
    unittest.main()
