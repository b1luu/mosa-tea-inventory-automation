import json
import unittest
from unittest.mock import patch

from app.lambda_oauth import lambda_handler


class LambdaOAuthTests(unittest.TestCase):
    def test_lambda_handler_returns_redirect_for_oauth_start(self):
        event = {
            "requestContext": {"http": {"method": "GET", "path": "/oauth/square/start"}},
            "rawPath": "/oauth/square/start",
            "rawQueryString": "environment=sandbox",
            "headers": {},
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

    def test_lambda_handler_returns_html_error_for_callback_failure(self):
        event = {
            "requestContext": {
                "http": {"method": "GET", "path": "/oauth/square/callback"}
            },
            "rawPath": "/oauth/square/callback",
            "rawQueryString": "error=access_denied&error_description=Seller+denied+access",
            "headers": {},
        }

        result = lambda_handler(event, context=None)

        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(result["headers"]["content-type"], "text/html; charset=utf-8")
        self.assertIn("Square OAuth Error", result["body"])
        self.assertIn("access_denied", result["body"])

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
