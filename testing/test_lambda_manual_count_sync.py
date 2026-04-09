from decimal import Decimal
import base64
import json
import unittest
from unittest.mock import patch

from app.lambda_manual_count_sync import lambda_handler


class LambdaManualCountSyncTests(unittest.TestCase):
    def test_lambda_handler_processes_batch_request(self):
        event = {
            "headers": {"X-Operator-Token": "token-1"},
            "body": json.dumps(
                {
                    "environment": "sandbox",
                    "merchant_id": "merchant-1",
                    "location_id": "location-1",
                    "apply_changes": True,
                    "rows": [
                        {
                            "inventory_key": "black_tea",
                            "counted_quantity": "12",
                            "counted_unit": "bag",
                            "source_reference": "Sheet1!AG2",
                        }
                    ],
                }
            ),
            "isBase64Encoded": False,
        }

        with (
            patch("app.lambda_manual_count_sync.get_operator_api_token", return_value="token-1"),
            patch(
                "app.lambda_manual_count_sync.sync_manual_inventory_counts_batch",
                return_value={"summary": {"total_rows": 1}},
            ) as mock_sync,
        ):
            result = lambda_handler(event, context=None)

        mock_sync.assert_called_once_with(
            environment="sandbox",
            merchant_id="merchant-1",
            location_id="location-1",
            rows=[
                {
                    "inventory_key": "black_tea",
                    "counted_quantity": "12",
                    "counted_unit": "bag",
                    "source_reference": "Sheet1!AG2",
                }
            ],
            apply_changes=True,
        )
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(json.loads(result["body"]), {"summary": {"total_rows": 1}})

    def test_lambda_handler_serializes_decimal_batch_fields(self):
        event = {
            "headers": {"X-Operator-Token": "token-1"},
            "body": json.dumps(
                {
                    "environment": "sandbox",
                    "merchant_id": "merchant-1",
                    "location_id": "location-1",
                    "apply_changes": False,
                    "rows": [
                        {
                            "inventory_key": "black_tea",
                            "counted_quantity": "12",
                            "counted_unit": "bag",
                            "source_reference": "Sheet1!AG2",
                        }
                    ],
                }
            ),
            "isBase64Encoded": False,
        }

        service_result = {
            "summary": {"total_rows": 1, "changed_rows": 0, "unchanged_rows": 1},
            "rows": [
                {
                    "inventory_key": "black_tea",
                    "counted_quantity": Decimal("12"),
                    "counted_unit": "bag",
                    "delta": {"in_stock_quantity": Decimal("0")},
                }
            ],
        }

        with (
            patch("app.lambda_manual_count_sync.get_operator_api_token", return_value="token-1"),
            patch(
                "app.lambda_manual_count_sync.sync_manual_inventory_counts_batch",
                return_value=service_result,
            ),
        ):
            result = lambda_handler(event, context=None)

        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(
            json.loads(result["body"]),
            {
                "summary": {"total_rows": 1, "changed_rows": 0, "unchanged_rows": 1},
                "rows": [
                    {
                        "inventory_key": "black_tea",
                        "counted_quantity": "12",
                        "counted_unit": "bag",
                        "delta": {"in_stock_quantity": "0"},
                    }
                ],
            },
        )

    def test_lambda_handler_rejects_missing_operator_token(self):
        event = {
            "headers": {},
            "body": "{}",
            "isBase64Encoded": False,
        }

        with (
            patch("app.lambda_manual_count_sync.get_operator_api_token", return_value="token-1"),
            patch("app.lambda_manual_count_sync.sync_manual_inventory_counts_batch") as mock_sync,
        ):
            result = lambda_handler(event, context=None)

        mock_sync.assert_not_called()
        self.assertEqual(result["statusCode"], 401)
        self.assertEqual(
            json.loads(result["body"]),
            {"detail": "Invalid or missing operator token."},
        )

    def test_lambda_handler_decodes_base64_body_and_reports_missing_fields(self):
        raw_body = json.dumps({"environment": "sandbox", "rows": []})
        event = {
            "headers": {"Authorization": "Bearer token-1"},
            "body": base64.b64encode(raw_body.encode("utf-8")).decode("ascii"),
            "isBase64Encoded": True,
        }

        with patch("app.lambda_manual_count_sync.get_operator_api_token", return_value="token-1"):
            result = lambda_handler(event, context=None)

        self.assertEqual(result["statusCode"], 400)
        self.assertEqual(
            json.loads(result["body"]),
            {"detail": "Missing required field: merchant_id"},
        )


if __name__ == "__main__":
    unittest.main()
