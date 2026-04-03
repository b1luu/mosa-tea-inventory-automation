import unittest
from decimal import Decimal

from testing.run_live_cloud_canary import (
    _inventory_mismatches,
    _normalize_usage_by_inventory_key,
    _pipeline_has_terminal_failure,
    _pipeline_is_settled,
    _summarize_webhook_events,
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


if __name__ == "__main__":
    unittest.main()
