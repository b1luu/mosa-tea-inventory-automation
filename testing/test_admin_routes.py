import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class AdminRoutesTests(unittest.TestCase):
    def test_runtime_console_page_renders(self):
        client = TestClient(server.app)

        response = client.get("/admin/console")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Mosa Tea Backend Console", response.text)
        self.assertIn("Hidden Placeholder/Test Merchants", response.text)
        self.assertIn('/static/admin/runtime_console.js', response.text)

    def test_runtime_console_javascript_is_served(self):
        client = TestClient(server.app)

        response = client.get("/static/admin/runtime_console.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn("async function refresh()", response.text)

    def test_webhook_events_api_returns_store_rows(self):
        client = TestClient(server.app)

        with patch(
            "app.admin_routes.list_webhook_events",
            return_value=[{"event_id": "evt-1", "status": "processed"}],
        ):
            response = client.get("/admin/api/webhook-events")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"event_id": "evt-1", "status": "processed"}],
        )


if __name__ == "__main__":
    unittest.main()
