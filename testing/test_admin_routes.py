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


if __name__ == "__main__":
    unittest.main()
