import json
import os
import time
import unittest
from unittest.mock import patch

from app.lambda_oauth import lambda_handler
from app.operator_session import COOKIE_NAME as OPERATOR_SESSION_COOKIE, issue_session_value


_TEST_SIGNING_KEY = "test-signing-key-32-bytes-please-1234567890"


def _session_cookie_header():
    value, _ = issue_session_value(
        ttl_seconds=3600, signing_key=_TEST_SIGNING_KEY, now=int(time.time())
    )
    return f"{OPERATOR_SESSION_COOKIE}={value}"


class LambdaOAuthTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ,
            {"OPERATOR_SESSION_SIGNING_KEY": _TEST_SIGNING_KEY},
            clear=False,
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    def test_lambda_handler_merges_event_cookies_into_request_headers(self):
        # API Gateway HTTP API (v2) strips the request `Cookie` header into a
        # top-level `cookies` array. Our handler must merge it back so FastAPI's
        # request.cookies works — otherwise every cookie-based flow (operator
        # session, OAuth state cookies, etc.) silently fails because the
        # framework thinks there were no cookies on the request.
        value, _ = issue_session_value(
            ttl_seconds=3600, signing_key=_TEST_SIGNING_KEY, now=int(time.time())
        )
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/onboarding"}},
            "rawPath": "/onboarding",
            "rawQueryString": "",
            "headers": {},
            # API Gateway v2 sends cookies here, NOT in headers:
            "cookies": [f"{OPERATOR_SESSION_COOKIE}={value}"],
        }

        result = lambda_handler(event, context=None)

        # If the cookie was forwarded to FastAPI, /onboarding renders the
        # Connect page (authenticated). If it was ignored, /onboarding renders
        # the operator gate (unauthenticated).
        self.assertEqual(result["statusCode"], 200)
        self.assertIn("Connect Mosa Tea to Square", result["body"])
        self.assertNotIn("Operator access required", result["body"])

    def test_lambda_handler_returns_redirect_for_oauth_start(self):
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/oauth/square/start"}},
            "rawPath": "/oauth/square/start",
            "rawQueryString": "environment=sandbox",
            "headers": {"cookie": _session_cookie_header()},
        }

        with (
            patch("app.oauth_routes.create_oauth_state", return_value="state-123"),
            patch(
                "app.oauth_routes.build_square_oauth_authorization_url",
                return_value="https://square.example/authorize?state=state-123",
            ),
        ):
            result = lambda_handler(event, context=None)

        self.assertEqual(result["statusCode"], 302)
        self.assertEqual(
            result["headers"]["location"],
            "https://square.example/authorize?state=state-123",
        )

    def test_lambda_handler_returns_set_cookie_in_cookies_array_not_headers(self):
        # Regression: API Gateway HTTP API (v2 payload) drops Set-Cookie
        # entries stuffed into the `headers` dict. They must come back in the
        # top-level `cookies` array, otherwise the operator session cookie
        # never reaches the browser and the boss can't complete onboarding.
        event = {
            "requestContext": {"http": {"method": "POST", "path": "/onboarding"}},
            "rawPath": "/onboarding",
            "rawQueryString": "",
            "headers": {"content-type": "application/x-www-form-urlencoded"},
            "body": "op_token=test-operator-token",
        }

        with patch(
            "app.oauth_routes.get_operator_api_token",
            return_value="test-operator-token",
        ):
            result = lambda_handler(event, context=None)

        self.assertEqual(result["statusCode"], 303)
        self.assertIn("cookies", result)
        self.assertEqual(len(result["cookies"]), 1)
        self.assertIn("mosa_operator_session=", result["cookies"][0])
        self.assertIn("HttpOnly", result["cookies"][0])
        self.assertIn("Secure", result["cookies"][0])
        # And critically: Set-Cookie must NOT be in the headers dict (API
        # Gateway v2 would drop it there).
        self.assertNotIn("set-cookie", {k.lower() for k in result["headers"]})

    def test_lambda_handler_returns_html_error_for_callback_failure(self):
        event = {
            "requestContext": {
                "http": {"method": "GET", "path": "/oauth/square/callback"}
            },
            "rawPath": "/oauth/square/callback",
            "rawQueryString": "error=access_denied&error_description=Seller+denied+access",
            "headers": {"cookie": _session_cookie_header()},
        }

        result = lambda_handler(event, context=None)

        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(result["headers"]["content-type"], "text/html; charset=utf-8")
        self.assertIn("Connection cancelled", result["body"])
        self.assertIn("Nothing was connected", result["body"])

    def test_lambda_handler_returns_json_for_refresh_route(self):
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
        event = {
            "requestContext": {
                "http": {
                    "method": "POST",
                    "path": "/oauth/square/refresh/merchant-1",
                }
            },
            "rawPath": "/oauth/square/refresh/merchant-1",
            "rawQueryString": "environment=production",
            "headers": {"X-Operator-Token": "test-operator-token"},
        }

        with (
            patch("app.operator_auth.get_operator_api_token", return_value="test-operator-token"),
            patch(
                "app.oauth_routes.refresh_oauth_merchant_access_token",
                return_value=auth_record,
            ) as mock_refresh,
            patch(
                "app.oauth_routes.retrieve_token_status",
                return_value=token_status,
            ),
        ):
            result = lambda_handler(event, context=None)

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertTrue(body["refreshed"])
        self.assertEqual(body["merchant_id"], "merchant-1")
        self.assertNotIn("access_token", body["auth"])
        mock_refresh.assert_called_once_with("production", "merchant-1", force=True)


if __name__ == "__main__":
    unittest.main()
