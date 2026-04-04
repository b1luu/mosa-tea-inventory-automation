import unittest
from unittest.mock import patch

from app.merchant_store import MerchantContext
from scripts.list_connected_merchants import _build_report, _parse_args


class ListConnectedMerchantsTests(unittest.TestCase):
    def test_parse_args_supports_environment_status_and_verify_live(self):
        environment, status, verify_live = _parse_args(
            ["--environment", "production", "--status", "active", "--verify-live"]
        )

        self.assertEqual(environment, "production")
        self.assertEqual(status, "active")
        self.assertTrue(verify_live)

    def test_build_report_summarizes_local_connections(self):
        contexts = [
            MerchantContext(
                environment="production",
                merchant_id="merchant-1",
                status="active",
                auth_mode="oauth",
                location_id="LOC-1",
                writes_enabled=False,
                binding_version=2,
                display_name="Tea Shop LLC",
            )
        ]
        auth_record = {
            "source": "oauth",
            "token_type": "bearer",
            "expires_at": "2026-05-01T00:00:00Z",
            "short_lived": False,
            "scopes": ["ORDERS_READ", "INVENTORY_WRITE"],
            "refresh_token": "refresh-1",
            "updated_at": "2026-04-04T00:00:00Z",
        }

        with (
            patch(
                "scripts.list_connected_merchants.list_merchant_contexts",
                return_value=contexts,
            ),
            patch(
                "scripts.list_connected_merchants.get_merchant_auth_record",
                return_value=auth_record,
            ),
        ):
            report = _build_report(environment="production", verify_live=False)

        self.assertEqual(report["summary"]["merchant_count"], 1)
        self.assertEqual(report["merchants"][0]["merchant_id"], "merchant-1")
        self.assertTrue(report["merchants"][0]["auth"]["has_refresh_token"])
        self.assertNotIn("live", report["merchants"][0])

    def test_build_report_can_include_live_verification(self):
        contexts = [
            MerchantContext(
                environment="production",
                merchant_id="merchant-1",
                status="active",
                auth_mode="oauth",
                location_id="LOC-1",
                writes_enabled=False,
                binding_version=None,
                display_name="Tea Shop LLC",
            )
        ]

        with (
            patch(
                "scripts.list_connected_merchants.list_merchant_contexts",
                return_value=contexts,
            ),
            patch(
                "scripts.list_connected_merchants.get_merchant_auth_record",
                return_value=None,
            ),
            patch(
                "scripts.list_connected_merchants._verify_live_connection",
                return_value={"verified": True, "location_count": 1, "locations": []},
            ),
        ):
            report = _build_report(verify_live=True)

        self.assertTrue(report["merchants"][0]["live"]["verified"])


if __name__ == "__main__":
    unittest.main()
