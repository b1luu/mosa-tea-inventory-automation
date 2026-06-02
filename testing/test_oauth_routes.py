import time
import unittest
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from app.merchant_store import MerchantContext
from app.operator_session import COOKIE_NAME as OPERATOR_SESSION_COOKIE, issue_session_value


_TEST_SIGNING_KEY = "test-signing-key-32-bytes-please-1234567890"


def _valid_session_cookies():
    value, _ = issue_session_value(
        ttl_seconds=3600, signing_key=_TEST_SIGNING_KEY, now=int(time.time())
    )
    return {OPERATOR_SESSION_COOKIE: value}


class OAuthRouteTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ,
            {
                "OPERATOR_API_TOKEN": "test-operator-token",
                "OPERATOR_SESSION_SIGNING_KEY": _TEST_SIGNING_KEY,
            },
            clear=False,
        )
        self.env_patch.start()
        self.client = TestClient(server.app)

    def tearDown(self):
        self.env_patch.stop()

    def test_oauth_start_with_valid_session_redirects_to_square(self):
        with (
            patch("app.oauth_routes.create_oauth_state", return_value="state-123"),
            patch(
                "app.oauth_routes.build_square_oauth_authorization_url",
                return_value="https://square.example/authorize?state=state-123",
            ),
        ):
            response = self.client.get(
                "/oauth/square/start",
                cookies=_valid_session_cookies(),
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["location"],
            "https://square.example/authorize?state=state-123",
        )

    def test_oauth_start_without_session_redirects_to_onboarding(self):
        # The browser flow is now gated on the operator session cookie. No
        # session means we bounce back to /onboarding rather than initiating
        # Square OAuth on behalf of whoever shows up at the URL.
        response = self.client.get("/oauth/square/start", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/onboarding")

    def test_oauth_callback_renders_connection_cancelled_on_deny(self):
        response = self.client.get(
            "/oauth/square/callback",
            cookies=_valid_session_cookies(),
            params={
                "error": "access_denied",
                "error_description": "Seller denied access",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Connection cancelled", response.text)
        self.assertIn("Nothing was connected", response.text)

    def test_oauth_callback_escapes_error_content(self):
        response = self.client.get(
            "/oauth/square/callback",
            cookies=_valid_session_cookies(),
            params={
                "error": "weird_error",  # not access_denied -> falls into generic Authorization failed
                "error_description": "<script>alert(1)</script>",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("<script>alert(1)</script>", response.text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", response.text)

    def test_oauth_callback_without_session_renders_session_expired(self):
        response = self.client.get(
            "/oauth/square/callback",
            params={"code": "code-123", "state": "state-123"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Operator session expired", response.text)

    def test_oauth_callback_rejects_invalid_state(self):
        with patch("app.oauth_routes.consume_oauth_state", return_value=None):
            response = self.client.get(
                "/oauth/square/callback",
                cookies=_valid_session_cookies(),
                params={"code": "code-123", "state": "bad-state"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Authorization expired", response.text)

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
                cookies=_valid_session_cookies(),
                params={"code": "code-123", "state": "state-123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Access granted", response.text)
        self.assertIn("API access to your Square account", response.text)
        self.assertIn("Tea Shop LLC", response.text)
        self.assertIn("merchant-1", response.text)
        self.assertIn("production", response.text)
        self.assertIn("MERCHANT_PROFILE_READ", response.text)
        # Old (incorrect) framing must not regress.
        self.assertNotIn("linked to Square", response.text)
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
        ), patch(
            "app.oauth_routes.get_merchant_write_readiness",
            return_value={
                "write_ready": False,
                "write_blockers": ["writes_disabled_by_operator", "missing_approved_binding"],
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
        self.assertFalse(merchants[0]["write_ready"])
        self.assertEqual(
            merchants[0]["write_blockers"],
            ["writes_disabled_by_operator", "missing_approved_binding"],
        )
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


class OnboardingRouteTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ,
            {
                "OPERATOR_API_TOKEN": "test-operator-token",
                "OPERATOR_SESSION_SIGNING_KEY": _TEST_SIGNING_KEY,
            },
            clear=False,
        )
        self.env_patch.start()
        self.client = TestClient(server.app)

    def tearDown(self):
        self.env_patch.stop()

    def test_get_onboarding_without_cookie_shows_operator_gate(self):
        response = self.client.get("/onboarding")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Operator access required", response.text)
        self.assertIn("name='op_token'", response.text)
        # The connect button should NOT yet be visible.
        self.assertNotIn("Connect to Square", response.text)

    def test_get_onboarding_with_valid_session_shows_connect_button(self):
        response = self.client.get("/onboarding", cookies=_valid_session_cookies())
        self.assertEqual(response.status_code, 200)
        self.assertIn("Connect to Square", response.text)
        self.assertIn("/oauth/square/start", response.text)
        # Operator gate form should NOT be present.
        self.assertNotIn("name='op_token'", response.text)

    def test_post_onboarding_with_wrong_token_rerenders_gate_with_error(self):
        response = self.client.post(
            "/onboarding",
            data={"op_token": "not-the-real-token"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("Operator access required", response.text)
        self.assertIn("didn&#x27;t match", response.text)
        # No session cookie should have been issued.
        self.assertNotIn(OPERATOR_SESSION_COOKIE, response.cookies)

    def test_post_onboarding_with_correct_token_sets_cookie_and_redirects(self):
        response = self.client.post(
            "/onboarding",
            data={"op_token": "test-operator-token"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/onboarding")
        # The Set-Cookie header should carry our session cookie with the
        # security attributes we designed.
        set_cookie = response.headers.get("set-cookie", "")
        self.assertIn(OPERATOR_SESSION_COOKIE, set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("Secure", set_cookie)
        self.assertIn("SameSite=lax", set_cookie)

    def test_post_onboarding_uses_constant_time_comparison(self):
        # Two near-miss tokens (one trailing char off + same length) both
        # produce the same "didn't match" response; this is mostly a
        # behavioural check that wrong tokens never leak whether they were
        # close.
        for wrong in ["test-operator-tokeX", "test-operator-toke", "x" * 20]:
            response = self.client.post(
                "/onboarding",
                data={"op_token": wrong},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 401, msg=f"wrong={wrong!r}")


if __name__ == "__main__":
    unittest.main()
