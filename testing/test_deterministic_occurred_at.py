import unittest
from datetime import datetime, timedelta, timezone

from app.order_processor import OCCURRED_AT_MAX_AGE, deterministic_occurred_at

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _summary(created_at):
    return {"order_id": f"order-{created_at}", "created_at": created_at}


class DeterministicOccurredAtTests(unittest.TestCase):
    def test_uses_the_orders_created_at_unchanged(self):
        self.assertEqual(
            deterministic_occurred_at([_summary("2026-11-20T11:50:00.123Z")], now=NOW),
            "2026-11-20T11:50:00.123Z",
        )

    def test_same_order_gives_the_same_value_at_different_times(self):
        summaries = [_summary("2026-11-20T11:50:00Z")]
        first = deterministic_occurred_at(summaries, now=NOW)
        later = deterministic_occurred_at(summaries, now=NOW + timedelta(hours=2))
        self.assertEqual(first, later)

    def test_several_orders_use_the_latest(self):
        summaries = [_summary("2026-11-20T09:00:00Z"), _summary("2026-11-20T11:00:00Z")]
        self.assertEqual(deterministic_occurred_at(summaries, now=NOW), "2026-11-20T11:00:00Z")

    def test_older_than_the_window_falls_back(self):
        old = (NOW - OCCURRED_AT_MAX_AGE - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        self.assertIsNone(deterministic_occurred_at([_summary(old)], now=NOW))

    def test_just_inside_the_window_is_kept(self):
        recent = (NOW - OCCURRED_AT_MAX_AGE + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        self.assertEqual(deterministic_occurred_at([_summary(recent)], now=NOW), recent)

    def test_window_is_inside_squares_24_hours(self):
        self.assertLess(OCCURRED_AT_MAX_AGE, timedelta(hours=24))

    def test_future_missing_or_unparseable_created_at_falls_back(self):
        for created_at in ("2026-11-20T12:05:00Z", None, "", "yesterday", "2026-11-20T11:00:00"):
            with self.subTest(created_at=created_at):
                self.assertIsNone(deterministic_occurred_at([_summary(created_at)], now=NOW))

    def test_no_orders_falls_back(self):
        self.assertIsNone(deterministic_occurred_at([], now=NOW))


if __name__ == "__main__":
    unittest.main()
