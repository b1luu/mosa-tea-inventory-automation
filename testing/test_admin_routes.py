import unittest
from unittest.mock import patch
import os

from fastapi.testclient import TestClient

import server


class AdminRoutesTests(unittest.TestCase):
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

    def test_order_processing_api_requires_operator_token(self):
        response = self.client.get("/admin/api/order-processing")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Invalid or missing operator token.",
        )

    def test_webhook_events_api_returns_store_rows(self):
        with patch(
            "app.admin_routes.list_webhook_events",
            return_value=[{"event_id": "evt-1", "status": "processed"}],
        ):
            response = self.client.get(
                "/admin/api/webhook-events",
                headers={"X-Operator-Token": "test-operator-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"event_id": "evt-1", "status": "processed"}],
        )

    def test_webhook_events_api_rejects_invalid_operator_token(self):
        response = self.client.get(
            "/admin/api/webhook-events",
            headers={"X-Operator-Token": "wrong-token"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Invalid or missing operator token.",
        )

    def test_order_processing_api_returns_store_rows(self):
        with patch(
            "app.admin_routes.list_order_processing_rows",
            return_value=[{"square_order_id": "order-1", "processing_state": "applied"}],
        ):
            response = self.client.get(
                "/admin/api/order-processing",
                headers={"X-Operator-Token": "test-operator-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"square_order_id": "order-1", "processing_state": "applied"}],
        )

    def test_manual_count_sync_endpoint_returns_service_result(self):
        with patch(
            "app.admin_routes.sync_manual_inventory_count",
            return_value={
                "inventory_key": "black_tea",
                "counted_quantity": "75.00000",
                "mode": {"apply": False},
            },
        ) as mock_sync:
            response = self.client.post(
                "/admin/api/manual-count-sync",
                headers={"X-Operator-Token": "test-operator-token"},
                json={
                    "environment": "sandbox",
                    "merchant_id": "merchant-1",
                    "location_id": "LOC-1",
                    "inventory_key": "black_tea",
                    "counted_quantity": 75,
                    "counted_unit": "bag",
                    "apply_changes": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["inventory_key"], "black_tea")
        mock_sync.assert_called_once_with(
            environment="sandbox",
            merchant_id="merchant-1",
            location_id="LOC-1",
            inventory_key="black_tea",
            counted_quantity=75,
            counted_unit="bag",
            apply_changes=False,
            source_reference=None,
        )

    def test_manual_count_sync_batch_endpoint_returns_service_result(self):
        with patch(
            "app.admin_routes.sync_manual_inventory_counts_batch",
            return_value={
                "summary": {
                    "total_rows": 2,
                    "changed_rows": 1,
                    "unchanged_rows": 1,
                },
                "rows": [
                    {"inventory_key": "black_tea", "result": "changed"},
                    {"inventory_key": "green_tea", "result": "unchanged"},
                ],
                "mode": {"apply": True},
            },
        ) as mock_sync:
            response = self.client.post(
                "/admin/api/manual-count-sync-batch",
                headers={"X-Operator-Token": "test-operator-token"},
                json={
                    "environment": "sandbox",
                    "merchant_id": "merchant-1",
                    "location_id": "LOC-1",
                    "apply_changes": True,
                    "rows": [
                        {
                            "inventory_key": "black_tea",
                            "counted_quantity": 75,
                            "counted_unit": "bag",
                            "source_reference": "Sheet1!AG2",
                        },
                        {
                            "inventory_key": "green_tea",
                            "counted_quantity": 12,
                            "counted_unit": "bag",
                            "source_reference": "Sheet1!AG3",
                        },
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["summary"]["total_rows"], 2)
        mock_sync.assert_called_once_with(
            environment="sandbox",
            merchant_id="merchant-1",
            location_id="LOC-1",
            rows=[
                {
                    "inventory_key": "black_tea",
                    "counted_quantity": 75,
                    "counted_unit": "bag",
                    "source_reference": "Sheet1!AG2",
                },
                {
                    "inventory_key": "green_tea",
                    "counted_quantity": 12,
                    "counted_unit": "bag",
                    "source_reference": "Sheet1!AG3",
                },
            ],
            apply_changes=True,
        )


if __name__ == "__main__":
    unittest.main()
