import unittest
from datetime import date
from zoneinfo import ZoneInfo

from app.shop_time import local_day_of, local_day_window

PACIFIC = ZoneInfo("America/Los_Angeles")


class LocalDayTests(unittest.TestCase):
    def test_evening_sale_counts_on_the_california_day(self):
        # 10:30 pm PDT on Oct 17 is already Oct 18 in UTC.
        self.assertEqual(local_day_of("2026-10-18T05:30:00.123Z", PACIFIC), "2026-10-17")

    def test_window_runs_midnight_to_midnight_pacific_in_summer_time(self):
        start, end, days = local_day_window(2, PACIFIC, today=date(2026, 10, 17))

        self.assertEqual(days, ["2026-10-16", "2026-10-17"])
        self.assertEqual(start, "2026-10-16T07:00:00.000Z")
        self.assertEqual(end, "2026-10-18T07:00:00.000Z")

    def test_window_follows_the_switch_to_standard_time(self):
        # DST ends Nov 1, 2026: that local day starts at UTC-7 and the next at UTC-8.
        start, end, days = local_day_window(1, PACIFIC, today=date(2026, 11, 1))

        self.assertEqual(days, ["2026-11-01"])
        self.assertEqual(start, "2026-11-01T07:00:00.000Z")
        self.assertEqual(end, "2026-11-02T08:00:00.000Z")

    def test_bounds_sort_correctly_against_millisecond_sale_times(self):
        start, end, _ = local_day_window(1, PACIFIC, today=date(2026, 10, 17))

        self.assertLess(start, "2026-10-17T07:00:00.001Z")
        self.assertLess("2026-10-18T06:59:59.999Z", end)
        self.assertFalse("2026-10-18T07:00:00.000Z" < end)


if __name__ == "__main__":
    unittest.main()
