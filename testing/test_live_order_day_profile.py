import unittest
from decimal import Decimal

from testing.create_live_test_order import MAX_REFERENCE_ID_LENGTH
from testing.live_order_day_profile import (
    build_day_profile_orders,
    build_dispatch_schedule,
    build_operational_drill_commands,
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

    def test_peak_day_first_slice_is_interleaved_not_grouped(self):
        planned_orders = build_day_profile_orders("sandbox_peak_day_200", limit=15)
        first_scenarios = [planned_order["scenario_name"] for planned_order in planned_orders]

        self.assertGreaterEqual(len(set(first_scenarios[:10])), 8)
        self.assertEqual(first_scenarios[0], "signature_black_milk_tea")
        self.assertEqual(first_scenarios[1], "signature_black_milk_tea")
        self.assertEqual(first_scenarios[2], "signature_black_milk_tea_boba")
        self.assertNotEqual(first_scenarios[:10], ["signature_black_milk_tea"] * 10)

    def test_list_day_profiles_includes_peak_day_summary(self):
        profiles = {
            profile["profile_name"]: profile for profile in list_day_profiles()
        }

        self.assertIn("sandbox_peak_day_200", profiles)
        self.assertEqual(profiles["sandbox_peak_day_200"]["total_drinks"], 200)
        self.assertIn("sandbox_canary_mix_40", profiles)
        self.assertEqual(profiles["sandbox_canary_mix_40"]["total_drinks"], 40)
        self.assertIn("sandbox_historical_fixture_day_200", profiles)
        self.assertEqual(profiles["sandbox_historical_fixture_day_200"]["total_drinks"], 200)

    def test_peak_day_projection_consumes_200_cups(self):
        combined_usage = project_day_profile_usage("sandbox_peak_day_200")
        usage_by_key = {
            usage["inventory_key"]: Decimal(str(usage["total_amount"]))
            for usage in combined_usage
        }

        self.assertEqual(usage_by_key["u600_cup"], Decimal("200"))
        self.assertGreater(usage_by_key["big_straw"], Decimal("0"))

    def test_canary_profile_supports_offset_batches(self):
        planned_orders = build_day_profile_orders(
            "sandbox_canary_mix_40",
            offset=8,
            limit=12,
        )

        self.assertEqual(len(planned_orders), 12)
        self.assertEqual(planned_orders[0]["sequence"], 9)
        self.assertEqual(planned_orders[-1]["sequence"], 20)

    def test_peak_day_drill_commands_mix_batches_and_checks(self):
        commands = build_operational_drill_commands("sandbox_peak_day_200")
        pay_batch_commands = [
            command for command in commands if command["action"] == "pay_batch"
        ]

        self.assertEqual(len(pay_batch_commands), 6)
        self.assertEqual(pay_batch_commands[0]["offset"], 0)
        self.assertEqual(pay_batch_commands[0]["limit"], 12)
        self.assertEqual(pay_batch_commands[-1]["offset"], 132)
        self.assertEqual(pay_batch_commands[-1]["limit"], 44)
        self.assertTrue(
            any(command["action"] == "check_main_queue" for command in commands)
        )
        self.assertTrue(
            any(command["action"] == "tail_worker_logs" for command in commands)
        )

    def test_peak_day_dispatch_schedule_spreads_batches_over_time(self):
        schedule = build_dispatch_schedule("sandbox_peak_day_200", schedule_scale=0.1)

        self.assertEqual(len(schedule), 6)
        self.assertEqual(schedule[0]["offset"], 0)
        self.assertEqual(schedule[0]["limit"], 12)
        self.assertEqual(schedule[1]["offset"], 12)
        self.assertEqual(schedule[1]["limit"], 18)
        self.assertEqual(schedule[1]["dispatch_offset_minutes"], "30")
        self.assertEqual(schedule[1]["wait_since_previous_minutes"], "30")
        self.assertEqual(schedule[1]["sleep_before_seconds"], "180.0")
        self.assertEqual(schedule[-1]["dispatch_offset_minutes"], "360")

    def test_canary_dispatch_schedule_matches_all_orders(self):
        schedule = build_dispatch_schedule("sandbox_canary_mix_40")

        self.assertEqual(sum(batch["limit"] for batch in schedule), 32)
        self.assertEqual(schedule[0]["dispatch_offset_minutes"], "0")
        self.assertEqual(schedule[1]["dispatch_offset_minutes"], "20")
        self.assertEqual(schedule[2]["dispatch_offset_minutes"], "45")

    def test_historical_fixture_profile_caps_at_200_drinks(self):
        summary = summarize_day_profile(
            "sandbox_historical_fixture_day_200",
            include_projected_usage=False,
        )

        self.assertEqual(summary["total_orders"], 172)
        self.assertEqual(summary["total_drinks"], 200)

    def test_historical_fixture_profile_uses_fixture_sources(self):
        planned_orders = build_day_profile_orders(
            "sandbox_historical_fixture_day_200",
            limit=10,
        )

        self.assertEqual(len(planned_orders), 10)
        self.assertTrue(
            all(planned_order["source_kind"] == "fixture" for planned_order in planned_orders)
        )
        self.assertTrue(
            any(
                planned_order["source_name"] == "completed_grapefruit_bloom_matcha.json"
                for planned_order in planned_orders
            )
        )


if __name__ == "__main__":
    unittest.main()
