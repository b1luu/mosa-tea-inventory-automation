import unittest
from decimal import Decimal

from testing.create_live_test_order import MAX_REFERENCE_ID_LENGTH
from testing.live_order_day_profile import (
    build_day_profile_orders,
    list_day_profiles,
    project_day_profile_usage,
    summarize_day_profile,
)


class LiveOrderDayProfileTests(unittest.TestCase):
    def test_peak_day_profile_caps_at_200_drinks(self):
        summary = summarize_day_profile("sandbox_peak_day_200", include_projected_usage=False)

        self.assertEqual(summary["total_orders"], 176)
        self.assertEqual(summary["total_drinks"], 200)

    def test_peak_day_profile_breakdown_tracks_multi_drink_orders(self):
        summary = summarize_day_profile("sandbox_peak_day_200", include_projected_usage=False)
        breakdown = {
            item["scenario_name"]: item for item in summary["scenario_breakdown"]
        }

        self.assertEqual(
            breakdown["grapefruit_bloom_and_matcha"]["order_count"],
            12,
        )
        self.assertEqual(
            breakdown["grapefruit_bloom_and_matcha"]["drinks_per_order"],
            3,
        )
        self.assertEqual(
            breakdown["grapefruit_bloom_and_matcha"]["total_drinks"],
            36,
        )

    def test_peak_day_orders_have_unique_bounded_reference_ids(self):
        planned_orders = build_day_profile_orders("sandbox_peak_day_200", limit=25)

        self.assertEqual(len(planned_orders), 25)
        reference_ids = [
            planned_order["order_payload"]["reference_id"]
            for planned_order in planned_orders
        ]
        self.assertEqual(len(reference_ids), len(set(reference_ids)))
        self.assertTrue(
            all(len(reference_id) <= MAX_REFERENCE_ID_LENGTH for reference_id in reference_ids)
        )

    def test_list_day_profiles_includes_peak_day_summary(self):
        profiles = {
            profile["profile_name"]: profile for profile in list_day_profiles()
        }

        self.assertIn("sandbox_peak_day_200", profiles)
        self.assertEqual(profiles["sandbox_peak_day_200"]["total_drinks"], 200)

    def test_peak_day_projection_consumes_200_cups(self):
        combined_usage = project_day_profile_usage("sandbox_peak_day_200")
        usage_by_key = {
            usage["inventory_key"]: Decimal(str(usage["total_amount"]))
            for usage in combined_usage
        }

        self.assertEqual(usage_by_key["u600_cup"], Decimal("200"))
        self.assertGreater(usage_by_key["big_straw"], Decimal("0"))


if __name__ == "__main__":
    unittest.main()
