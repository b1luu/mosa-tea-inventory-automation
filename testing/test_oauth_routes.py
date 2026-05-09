import unittest
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from app.merchant_store import MerchantContext


class OAuthRouteTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ,
            {"OPERATOR_API_TOKEN": "test-operator-token"},
            clear=False,
        )
        self.env_patch.start()
        self.client = TestClient(server.app)

    def tearDown(self):
        self.env_patch.stop()

    def test_oauth_start_redirects_to_square_authorization_url(self):
        with (
            patch("app.oauth_routes.create_oauth_state", return_value="state-123"),
            patch(
                "app.oauth_routes.build_square_oauth_authorization_url",
                return_value="https://square.example/authorize?state=state-123",
            ),
        ):
            response = self.client.get(
                "/oauth/square/start",
                params={"operator_token": "test-operator-token"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "https://square.example/authorize?state=state-123",
        )

    def test_oauth_start_requires_operator_token(self):
        response = self.client.get("/oauth/square/start", follow_redirects=False)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Invalid or missing operator token.",
        )

    def test_oauth_callback_returns_error_when_square_returns_error(self):
        response = self.client.get(
            "/oauth/square/callback",
            params={
                "error": "access_denied",
                "error_description": "Seller denied access",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Square OAuth Error", response.text)
        self.assertIn("access_denied", response.text)

    def test_oauth_callback_escapes_error_content(self):
        response = self.client.get(
            "/oauth/square/callback",
            params={
                "error": "<script>alert(1)</script>",
                "error_description": "<b>bad</b>",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("<script>alert(1)</script>", response.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", response.text)
        self.assertIn("&lt;b&gt;bad&lt;/b&gt;", response.text)

    def test_oauth_callback_rejects_invalid_state(self):
        with patch("app.oauth_routes.consume_oauth_state", return_value=None):
            response = self.client.get(
                "/oauth/square/callback",
                params={"code": "code-123", "state": "bad-state"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid or expired OAuth state.", response.text)

    def test_oauth_callback_stores_connected_merchant_summary(self):
        token_response = type(
            "TokenResponse",
            (),
            {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "merchant_id": "merchant-1",
                "token_type": "bearer",
                "expires_at": "2026-05-01T00:00:00Z",
                "short_lived": False,
            },
        )()
        token_status = type(
            "TokenStatus",
            (),
            {
                "merchant_id": "merchant-1",
                "client_id": "sq0idp-app",
                "expires_at": "2026-05-01T00:00:00Z",
                "scopes": ["MERCHANT_PROFILE_READ", "ORDERS_READ"],
            },
        )()
        locations = [
            type(
                "Location",
                (),
                {
                    "id": "LOC-1",
                    "name": "Tea Shop",
                    "business_name": "Tea Shop LLC",
                    "status": "ACTIVE",
                    "type": "PHYSICAL",
                },
            )()
        ]
        merchant_context = MerchantContext(
            environment="production",
            merchant_id="merchant-1",
            status="active",
            auth_mode="oauth",
            location_id="LOC-1",
            writes_enabled=False,
            binding_version=None,
            display_name="Tea Shop LLC",
        )

        with (
            patch(
                "app.oauth_routes.consume_oauth_state",
                return_value={"state": "state-123", "environment": "production"},
            ),
            patch(
                "app.oauth_routes.exchange_authorization_code",
                return_value=token_response,
            ),
            patch(
                "app.oauth_routes.retrieve_token_status",
                return_value=token_status,
            ),
            patch(
                "app.oauth_routes.list_locations_for_merchant",
                return_value=locations,
            ),
            patch(
                "app.oauth_routes.upsert_oauth_merchant",
                return_value=merchant_context,
            ) as mock_upsert,
        ):
            response = self.client.get(
                "/oauth/square/callback",
                params={"code": "code-123", "state": "state-123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Square OAuth Connected", response.text)
        self.assertIn("merchant_id: merchant-1", response.text)
        self.assertIn("selected_location_id: LOC-1", response.text)
        mock_upsert.assert_called_once()

    def test_oauth_status_lists_connected_merchants(self):
        with patch(
            "app.oauth_routes.list_merchant_contexts",
            return_value=[
                MerchantContext(
                    environment="production",
                    merchant_id="merchant-1",
                    status="active",
                    auth_mode="oauth",
                    location_id="LOC-1",
                    writes_enabled=False,
                    binding_version=3,
                    display_name="Tea Shop LLC",
                )
            ],
        ), patch(
            "app.oauth_routes.get_merchant_auth_record",
            return_value={
                "access_token": "secret-access",
                "refresh_token": "secret-refresh",
                "source": "oauth",
                "token_type": "bearer",
                "expires_at": "2026-05-01T00:00:00Z",
                "short_lived": False,
                "scopes": ["ORDERS_READ"],
                "updated_at": "2026-04-04T00:00:00Z",
            },
        ):
            response = self.client.get(
                "/oauth/square/status",
                headers={"X-Operator-Token": "test-operator-token"},
            )

        self.assertEqual(response.status_code, 200)
        merchants = response.json()["merchants"]
        self.assertEqual(len(merchants), 1)
        self.assertEqual(merchants[0]["merchant_id"], "merchant-1")
        self.assertEqual(merchants[0]["binding_version"], 3)
        self.assertTrue(merchants[0]["auth"]["has_refresh_token"])
        self.assertNotIn("access_token", merchants[0]["auth"])

    def test_oauth_status_requires_operator_token(self):
        response = self.client.get("/oauth/square/status")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Invalid or missing operator token.",
        )

    def test_oauth_refresh_endpoint_returns_updated_status(self):
        auth_record = {
            "environment": "production",
            "merchant_id": "merchant-1",
            "access_token": "access-2",
            "refresh_token": "refresh-1",
            "token_type": "bearer",
            "expires_at": "2026-05-01T00:00:00Z",
            "short_lived": False,
            "scopes": ["ORDERS_READ", "INVENTORY_WRITE"],
            "source": "oauth",
            "created_at": "2026-04-04T00:00:00Z",
            "updated_at": "2026-04-04T00:01:00Z",
        }
        token_status = type(
            "TokenStatus",
            (),
            {
                "merchant_id": "merchant-1",
                "client_id": "sq0idp-app",
                "expires_at": "2026-05-01T00:00:00Z",
                "scopes": ["ORDERS_READ", "INVENTORY_WRITE"],
            },
        )()

        with (
            patch(
                "app.oauth_routes.refresh_oauth_merchant_access_token",
                return_value=auth_record,
            ) as mock_refresh,
            patch(
                "app.oauth_routes.retrieve_token_status",
                return_value=token_status,
            ),
        ):
            response = self.client.post(
                "/oauth/square/refresh/merchant-1?environment=production",
                headers={"X-Operator-Token": "test-operator-token"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["refreshed"])
        self.assertEqual(body["merchant_id"], "merchant-1")
        self.assertTrue(body["auth"]["has_refresh_token"])
        self.assertNotIn("access_token", body["auth"])
        mock_refresh.assert_called_once_with("production", "merchant-1", force=True)

    def test_oauth_refresh_requires_operator_token(self):
        response = self.client.post("/oauth/square/refresh/merchant-1")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Invalid or missing operator token.",
        )


if __name__ == "__main__":
    unittest.main()
