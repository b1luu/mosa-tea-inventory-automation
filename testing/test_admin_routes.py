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

    def test_runtime_console_page_renders(self):
        response = self.client.get(
            "/admin/console",
            params={"operator_token": "test-operator-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Mosa Tea Backend Console", response.text)
        self.assertIn("Hidden Placeholder/Test Merchants", response.text)
        self.assertIn('/static/admin/runtime_console.js', response.text)

    def test_runtime_console_page_requires_operator_token(self):
        response = self.client.get("/admin/console")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Invalid or missing operator token.",
        )

    def test_runtime_console_javascript_is_served(self):
        response = self.client.get("/static/admin/runtime_console.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn("operator_token", response.text)
        self.assertIn("async function refresh()", response.text)

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


if __name__ == "__main__":
    unittest.main()
