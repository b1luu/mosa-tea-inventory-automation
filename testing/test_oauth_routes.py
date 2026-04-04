import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from app.merchant_store import MerchantContext


class OAuthRouteTests(unittest.TestCase):
    def test_oauth_start_redirects_to_square_authorization_url(self):
        client = TestClient(server.app)

        with (
            patch("app.oauth_routes.create_oauth_state", return_value="state-123"),
            patch(
                "app.oauth_routes.build_square_oauth_authorization_url",
                return_value="https://square.example/authorize?state=state-123",
            ),
        ):
            response = client.get("/oauth/square/start", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "https://square.example/authorize?state=state-123",
        )

    def test_oauth_callback_returns_error_when_square_returns_error(self):
        client = TestClient(server.app)

        response = client.get(
            "/oauth/square/callback",
            params={
                "error": "access_denied",
                "error_description": "Seller denied access",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "access_denied")

    def test_oauth_callback_rejects_invalid_state(self):
        client = TestClient(server.app)

        with patch("app.oauth_routes.consume_oauth_state", return_value=None):
            response = client.get(
                "/oauth/square/callback",
                params={"code": "code-123", "state": "bad-state"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Invalid or expired OAuth state.")

    def test_oauth_callback_stores_connected_merchant_summary(self):
        client = TestClient(server.app)

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
            response = client.get(
                "/oauth/square/callback",
                params={"code": "code-123", "state": "state-123"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["connected"])
        self.assertEqual(body["merchant"]["merchant_id"], "merchant-1")
        self.assertEqual(body["merchant"]["selected_location_id"], "LOC-1")
        self.assertEqual(body["locations"][0]["id"], "LOC-1")
        mock_upsert.assert_called_once()

    def test_oauth_status_lists_connected_merchants(self):
        client = TestClient(server.app)

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
            response = client.get("/oauth/square/status")

        self.assertEqual(response.status_code, 200)
        merchants = response.json()["merchants"]
        self.assertEqual(len(merchants), 1)
        self.assertEqual(merchants[0]["merchant_id"], "merchant-1")
        self.assertEqual(merchants[0]["binding_version"], 3)
        self.assertTrue(merchants[0]["auth"]["has_refresh_token"])
        self.assertNotIn("access_token", merchants[0]["auth"])

    def test_oauth_refresh_endpoint_returns_updated_status(self):
        client = TestClient(server.app)

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
            response = client.post("/oauth/square/refresh/merchant-1?environment=production")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["refreshed"])
        self.assertEqual(body["merchant_id"], "merchant-1")
        self.assertTrue(body["auth"]["has_refresh_token"])
        self.assertNotIn("access_token", body["auth"])
        mock_refresh.assert_called_once_with("production", "merchant-1", force=True)


if __name__ == "__main__":
    unittest.main()
