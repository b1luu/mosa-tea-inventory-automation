import base64
import json
import unittest
from unittest.mock import patch

from app.lambda_webhook_ingress import lambda_handler
from app.webhook_ingress import WebhookIngressResponse


class LambdaWebhookIngressTests(unittest.TestCase):
    def test_lambda_handler_passes_raw_body_and_signature_header(self):
        event = {
            "headers": {"x-square-hmacsha256-signature": "sig-1"},
            "body": '{"hello":"world"}',
            "isBase64Encoded": False,
        }

        with patch(
            "app.lambda_webhook_ingress.handle_square_webhook_request",
            return_value=WebhookIngressResponse(status_code=200, body={"ok": True}),
        ) as mock_handler:
            result = lambda_handler(event, context=None)

        mock_handler.assert_called_once_with(
            request_body='{"hello":"world"}',
            signature_header="sig-1",
        )
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"]), {"ok": True})

    def test_lambda_handler_decodes_base64_request_body(self):
        raw_body = '{"hello":"world"}'
        event = {
            "headers": {"X-Square-HmacSha256-Signature": "sig-2"},
            "body": base64.b64encode(raw_body.encode("utf-8")).decode("ascii"),
            "isBase64Encoded": True,
        }

        with patch(
            "app.lambda_webhook_ingress.handle_square_webhook_request",
            return_value=WebhookIngressResponse(status_code=403, body={"error": "invalid signature"}),
        ) as mock_handler:
            result = lambda_handler(event, context=None)

        mock_handler.assert_called_once_with(
            request_body=raw_body,
            signature_header="sig-2",
        )
        self.assertEqual(result["statusCode"], 403)
        self.assertEqual(json.loads(result["body"]), {"error": "invalid signature"})
