import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


def _build_order_updated_payload():
    return {
        "merchant_id": "merchant-1",
        "location_id": "location-1",
        "type": "order.updated",
        "event_id": "evt-1",
        "created_at": "2026-03-31T12:00:00Z",
        "data": {
            "type": "event",
            "id": "data-1",
            "object": {
                "order_updated": {
                    "order_id": "order-1",
                    "state": "COMPLETED",
                    "location_id": "location-1",
                    "updated_at": "2026-03-31T12:00:01Z",
                    "version": 3,
                }
            },
        },
    }


def _build_catalog_updated_payload():
    return {
        "merchant_id": "merchant-1",
        "type": "catalog.version.updated",
        "event_id": "catalog-evt-1",
        "created_at": "2026-03-31T12:00:00Z",
        "data": {
            "type": "catalog_version",
            "id": "catalog-data-1",
            "object": {},
        },
    }


class ServerWebhookDispatchTests(unittest.TestCase):
    def setUp(self):
        self.signature_key_patcher = patch(
            "server.get_square_webhook_signature_key",
            return_value="test-signature-key",
        )
        self.notification_url_patcher = patch(
            "server.get_square_webhook_notification_url",
            return_value="https://example.com/webhook/square",
        )
        self.signature_key_patcher.start()
        self.notification_url_patcher.start()

    def tearDown(self):
        self.notification_url_patcher.stop()
        self.signature_key_patcher.stop()

    def test_marks_event_enqueued_only_after_dispatch_succeeds(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.get_order_processing_state", return_value=None):
                    with patch("server.reserve_order_processing", return_value=True):
                        with patch("server.record_webhook_event") as mock_record:
                            with patch("server.dispatch_webhook_job") as mock_dispatch:
                                with patch("server.set_webhook_event_status") as mock_status:
                                    response = client.post(
                                        "/webhook/square",
                                        data=json.dumps(payload),
                                        headers={"x-square-hmacsha256-signature": "ok"},
                                    )

        self.assertEqual(response.status_code, 200)
        mock_record.assert_called_once()
        self.assertEqual(
            mock_record.call_args.kwargs["status"], server.EVENT_STATUS_RECEIVED
        )
        mock_dispatch.assert_called_once()
        mock_status.assert_called_once_with("evt-1", server.EVENT_STATUS_ENQUEUED)

    def test_marks_event_failed_and_clears_reservation_when_dispatch_raises(self):
        client = TestClient(server.app, raise_server_exceptions=False)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.get_order_processing_state", return_value=None):
                    with patch("server.reserve_order_processing", return_value=True):
                        with patch("server.record_webhook_event") as mock_record:
                            with patch(
                                "server.dispatch_webhook_job",
                                side_effect=RuntimeError("dispatch exploded"),
                            ):
                                with patch(
                                    "server.clear_order_processing_reservation"
                                ) as mock_clear:
                                    with patch(
                                        "server.set_webhook_event_status"
                                    ) as mock_status:
                                        response = client.post(
                                            "/webhook/square",
                                            data=json.dumps(payload),
                                            headers={
                                                "x-square-hmacsha256-signature": "ok"
                                            },
                                        )

        self.assertEqual(response.status_code, 500)
        mock_record.assert_called_once()
        self.assertEqual(
            mock_record.call_args.kwargs["status"], server.EVENT_STATUS_RECEIVED
        )
        mock_clear.assert_called_once_with("order-1")
        mock_status.assert_called_once_with("evt-1", server.EVENT_STATUS_FAILED)

    def test_ignores_non_completed_order_event_without_dispatch(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()
        payload["data"]["object"]["order_updated"]["state"] = "OPEN"

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.get_order_processing_state", return_value=None):
                    with patch("server.record_webhook_event") as mock_record:
                        with patch("server.dispatch_webhook_job") as mock_dispatch:
                            with patch("server.set_webhook_event_status") as mock_status:
                                response = client.post(
                                    "/webhook/square",
                                    data=json.dumps(payload),
                                    headers={"x-square-hmacsha256-signature": "ok"},
                                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_record.call_args.kwargs["status"], server.EVENT_STATUS_IGNORED
        )
        mock_dispatch.assert_not_called()
        mock_status.assert_not_called()

    def test_ignores_completed_order_with_existing_processing_state(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.get_order_processing_state", return_value="applied"):
                    with patch("server.record_webhook_event") as mock_record:
                        with patch("server.dispatch_webhook_job") as mock_dispatch:
                            with patch("server.set_webhook_event_status") as mock_status:
                                response = client.post(
                                    "/webhook/square",
                                    data=json.dumps(payload),
                                    headers={"x-square-hmacsha256-signature": "ok"},
                                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_record.call_args.kwargs["status"], server.EVENT_STATUS_IGNORED
        )
        mock_dispatch.assert_not_called()
        mock_status.assert_not_called()

    def test_duplicate_order_event_is_not_re_recorded_or_dispatched(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch(
                "server.get_webhook_event",
                return_value={"event_id": "evt-1", "status": server.EVENT_STATUS_ENQUEUED},
            ):
                with patch("server.record_webhook_event") as mock_record:
                    with patch("server.dispatch_webhook_job") as mock_dispatch:
                        response = client.post(
                            "/webhook/square",
                            data=json.dumps(payload),
                            headers={"x-square-hmacsha256-signature": "ok"},
                        )

        self.assertEqual(response.status_code, 200)
        mock_record.assert_not_called()
        mock_dispatch.assert_not_called()

    def test_failed_event_is_allowed_to_retry_dispatch(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch(
                "server.get_webhook_event",
                return_value={"event_id": "evt-1", "status": server.EVENT_STATUS_FAILED},
            ):
                with patch("server.get_order_processing_state", return_value=None):
                    with patch("server.reserve_order_processing", return_value=True):
                        with patch("server.record_webhook_event") as mock_record:
                            with patch("server.dispatch_webhook_job") as mock_dispatch:
                                with patch("server.set_webhook_event_status") as mock_status:
                                    response = client.post(
                                        "/webhook/square",
                                        data=json.dumps(payload),
                                        headers={"x-square-hmacsha256-signature": "ok"},
                                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_record.call_args.kwargs["status"], server.EVENT_STATUS_RECEIVED
        )
        mock_dispatch.assert_called_once()
        mock_status.assert_called_once_with("evt-1", server.EVENT_STATUS_ENQUEUED)

    def test_completed_order_does_not_dispatch_when_reservation_is_lost(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch(
                    "server.get_order_processing_state",
                    side_effect=[None, "pending", "pending"],
                ):
                    with patch("server.reserve_order_processing", return_value=False):
                        with patch("server.record_webhook_event") as mock_record:
                            with patch("server.dispatch_webhook_job") as mock_dispatch:
                                with patch("server.set_webhook_event_status") as mock_status:
                                    response = client.post(
                                        "/webhook/square",
                                        data=json.dumps(payload),
                                        headers={"x-square-hmacsha256-signature": "ok"},
                                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_record.call_args.kwargs["status"], server.EVENT_STATUS_IGNORED
        )
        mock_dispatch.assert_not_called()
        mock_status.assert_not_called()

    def test_completed_order_without_event_id_dispatches_without_event_updates(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()
        payload.pop("event_id")

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_order_processing_state", return_value=None):
                with patch("server.reserve_order_processing", return_value=True):
                    with patch("server.record_webhook_event") as mock_record:
                        with patch("server.dispatch_webhook_job") as mock_dispatch:
                            with patch("server.set_webhook_event_status") as mock_status:
                                response = client.post(
                                    "/webhook/square",
                                    data=json.dumps(payload),
                                    headers={"x-square-hmacsha256-signature": "ok"},
                                )

        self.assertEqual(response.status_code, 200)
        mock_record.assert_not_called()
        mock_dispatch.assert_called_once()
        mock_status.assert_not_called()

    def test_catalog_event_marks_processed_when_no_changes_found(self):
        client = TestClient(server.app)
        payload = _build_catalog_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.record_webhook_event") as mock_record:
                    with patch("server.get_or_create_last_synced_at", return_value="2026-03-31T12:00:00Z"):
                        with patch("server.search_changed_catalog_objects", return_value=[]):
                            with patch("server.get_latest_updated_at", return_value=None):
                                with patch("server.set_webhook_event_status") as mock_status:
                                    response = client.post(
                                        "/webhook/square",
                                        data=json.dumps(payload),
                                        headers={"x-square-hmacsha256-signature": "ok"},
                                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_record.call_args.kwargs["status"], server.EVENT_STATUS_RECEIVED
        )
        mock_status.assert_called_once_with(
            "catalog-evt-1", server.EVENT_STATUS_PROCESSED
        )

    def test_catalog_event_marks_failed_when_processing_raises(self):
        client = TestClient(server.app, raise_server_exceptions=False)
        payload = _build_catalog_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.record_webhook_event") as mock_record:
                    with patch("server.get_or_create_last_synced_at", return_value="2026-03-31T12:00:00Z"):
                        with patch(
                            "server.search_changed_catalog_objects",
                            side_effect=RuntimeError("catalog exploded"),
                        ):
                            with patch("server.set_webhook_event_status") as mock_status:
                                response = client.post(
                                    "/webhook/square",
                                    data=json.dumps(payload),
                                    headers={"x-square-hmacsha256-signature": "ok"},
                                )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            mock_record.call_args.kwargs["status"], server.EVENT_STATUS_RECEIVED
        )
        mock_status.assert_called_once_with(
            "catalog-evt-1", server.EVENT_STATUS_FAILED
        )
