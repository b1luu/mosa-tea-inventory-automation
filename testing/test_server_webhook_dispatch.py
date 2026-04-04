import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from app.merchant_store import MerchantContext


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
        self.environment_patcher = patch(
            "server.get_square_environment_name",
            return_value="sandbox",
        )
        self.merchant_context_patcher = patch(
            "server.get_merchant_context",
            return_value=MerchantContext(
                environment="sandbox",
                merchant_id="merchant-1",
                status="active",
                auth_mode="oauth",
                location_id="location-1",
                writes_enabled=False,
                binding_version=None,
                display_name="Test Merchant",
            ),
        )
        self.signature_key_patcher.start()
        self.notification_url_patcher.start()
        self.environment_patcher.start()
        self.merchant_context_patcher.start()

    def tearDown(self):
        self.merchant_context_patcher.stop()
        self.environment_patcher.stop()
        self.notification_url_patcher.stop()
        self.signature_key_patcher.stop()

    def test_invalid_signature_rejects_before_json_parsing(self):
        client = TestClient(server.app)

        with patch("server.verify_signature", return_value=False):
            response = client.post(
                "/webhook/square",
                data="{not-json",
                headers={"x-square-hmacsha256-signature": "bad"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "invalid signature"})

    def test_marks_event_enqueued_only_after_dispatch_succeeds(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.get_order_processing_state", return_value=None):
                    with patch("server.reserve_order_processing", return_value=True):
                        with patch(
                            "server.create_webhook_event", return_value=True
                        ) as mock_create:
                            with patch("server.dispatch_webhook_job") as mock_dispatch:
                                with patch("server.set_webhook_event_status") as mock_status:
                                    response = client.post(
                                        "/webhook/square",
                                        data=json.dumps(payload),
                                        headers={"x-square-hmacsha256-signature": "ok"},
                                    )

        self.assertEqual(response.status_code, 200)
        mock_create.assert_called_once()
        self.assertEqual(
            mock_create.call_args.kwargs["status"], server.EVENT_STATUS_RECEIVED
        )
        mock_dispatch.assert_called_once_with(
            {
                "event_id": "evt-1",
                "merchant_id": "merchant-1",
                "environment": "sandbox",
                "event_type": "order.updated",
                "order_id": "order-1",
                "location_id": "location-1",
            },
            background_tasks=unittest.mock.ANY,
        )
        mock_status.assert_called_once_with("evt-1", server.EVENT_STATUS_ENQUEUED)

    def test_marks_event_failed_and_clears_reservation_when_dispatch_raises(self):
        client = TestClient(server.app, raise_server_exceptions=False)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.get_order_processing_state", return_value=None):
                    with patch("server.reserve_order_processing", return_value=True):
                        with patch(
                            "server.create_webhook_event", return_value=True
                        ) as mock_create:
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
        mock_create.assert_called_once()
        self.assertEqual(
            mock_create.call_args.kwargs["status"], server.EVENT_STATUS_RECEIVED
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
                    with patch(
                        "server.create_webhook_event", return_value=True
                    ) as mock_create:
                        with patch("server.dispatch_webhook_job") as mock_dispatch:
                            with patch("server.set_webhook_event_status") as mock_status:
                                response = client.post(
                                    "/webhook/square",
                                    data=json.dumps(payload),
                                    headers={"x-square-hmacsha256-signature": "ok"},
                                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_create.call_args.kwargs["status"], server.EVENT_STATUS_IGNORED
        )
        mock_dispatch.assert_not_called()
        mock_status.assert_not_called()

    def test_ignores_completed_order_with_existing_processing_state(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch("server.get_order_processing_state", return_value="applied"):
                    with patch(
                        "server.create_webhook_event", return_value=True
                    ) as mock_create:
                        with patch("server.dispatch_webhook_job") as mock_dispatch:
                            with patch("server.set_webhook_event_status") as mock_status:
                                response = client.post(
                                    "/webhook/square",
                                    data=json.dumps(payload),
                                    headers={"x-square-hmacsha256-signature": "ok"},
                                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_create.call_args.kwargs["status"], server.EVENT_STATUS_IGNORED
        )
        mock_dispatch.assert_not_called()
        mock_status.assert_not_called()

    def test_ignores_completed_order_when_merchant_context_is_missing(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_merchant_context", return_value=None):
                with patch("server.get_webhook_event", return_value=None):
                    with patch("server.get_order_processing_state", return_value=None):
                        with patch(
                            "server.create_webhook_event", return_value=True
                        ) as mock_create:
                            with patch("server.dispatch_webhook_job") as mock_dispatch:
                                with patch("server.set_webhook_event_status") as mock_status:
                                    response = client.post(
                                        "/webhook/square",
                                        data=json.dumps(payload),
                                        headers={"x-square-hmacsha256-signature": "ok"},
                                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_create.call_args.kwargs["status"], server.EVENT_STATUS_IGNORED
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
                with patch("server.create_webhook_event") as mock_create:
                    with patch("server.dispatch_webhook_job") as mock_dispatch:
                        response = client.post(
                            "/webhook/square",
                            data=json.dumps(payload),
                            headers={"x-square-hmacsha256-signature": "ok"},
                        )

        self.assertEqual(response.status_code, 200)
        mock_create.assert_not_called()
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
                        with patch("server.create_webhook_event") as mock_create:
                            with patch("server.dispatch_webhook_job") as mock_dispatch:
                                with patch("server.set_webhook_event_status") as mock_status:
                                    response = client.post(
                                        "/webhook/square",
                                        data=json.dumps(payload),
                                        headers={"x-square-hmacsha256-signature": "ok"},
                                    )

        self.assertEqual(response.status_code, 200)
        mock_create.assert_not_called()
        mock_dispatch.assert_called_once()
        self.assertEqual(
            mock_status.call_args_list,
            [
                unittest.mock.call("evt-1", server.EVENT_STATUS_RECEIVED),
                unittest.mock.call("evt-1", server.EVENT_STATUS_ENQUEUED),
            ],
        )

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
                        with patch(
                            "server.create_webhook_event", return_value=True
                        ) as mock_create:
                            with patch("server.dispatch_webhook_job") as mock_dispatch:
                                with patch("server.set_webhook_event_status") as mock_status:
                                    response = client.post(
                                        "/webhook/square",
                                        data=json.dumps(payload),
                                        headers={"x-square-hmacsha256-signature": "ok"},
                                    )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_create.call_args.kwargs["status"], server.EVENT_STATUS_RECEIVED
        )
        mock_dispatch.assert_not_called()
        mock_status.assert_called_once_with("evt-1", server.EVENT_STATUS_IGNORED)

    def test_atomic_event_create_loss_short_circuits_before_reserving_or_dispatching(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch(
                "server.get_webhook_event",
                side_effect=[
                    None,
                    {
                        "event_id": "evt-1",
                        "status": server.EVENT_STATUS_ENQUEUED,
                    },
                ],
            ):
                with patch("server.get_order_processing_state", return_value=None):
                    with patch(
                        "server.create_webhook_event", return_value=False
                    ) as mock_create:
                        with patch(
                            "server.reserve_order_processing"
                        ) as mock_reserve:
                            with patch("server.dispatch_webhook_job") as mock_dispatch:
                                response = client.post(
                                    "/webhook/square",
                                    data=json.dumps(payload),
                                    headers={
                                        "x-square-hmacsha256-signature": "ok"
                                    },
                                )

        self.assertEqual(response.status_code, 200)
        mock_create.assert_called_once()
        mock_reserve.assert_not_called()
        mock_dispatch.assert_not_called()

    def test_completed_order_without_event_id_dispatches_without_event_updates(self):
        client = TestClient(server.app)
        payload = _build_order_updated_payload()
        payload.pop("event_id")

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_order_processing_state", return_value=None):
                with patch("server.reserve_order_processing", return_value=True):
                    with patch("server.create_webhook_event") as mock_create:
                        with patch("server.dispatch_webhook_job") as mock_dispatch:
                            with patch("server.set_webhook_event_status") as mock_status:
                                response = client.post(
                                    "/webhook/square",
                                    data=json.dumps(payload),
                                    headers={"x-square-hmacsha256-signature": "ok"},
                                )

        self.assertEqual(response.status_code, 200)
        mock_create.assert_not_called()
        mock_dispatch.assert_called_once()
        mock_status.assert_not_called()

    def test_catalog_event_is_created_as_ignored_when_catalog_sync_is_disabled(self):
        client = TestClient(server.app)
        payload = _build_catalog_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch("server.get_webhook_event", return_value=None):
                with patch(
                    "server.create_webhook_event", return_value=True
                ) as mock_create:
                    with patch("server.set_webhook_event_status") as mock_status:
                        with patch("server.get_or_create_last_synced_at") as mock_get_checkpoint:
                            response = client.post(
                                "/webhook/square",
                                data=json.dumps(payload),
                                headers={"x-square-hmacsha256-signature": "ok"},
                            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            mock_create.call_args.kwargs["status"], server.EVENT_STATUS_IGNORED
        )
        mock_status.assert_not_called()
        mock_get_checkpoint.assert_not_called()

    def test_duplicate_catalog_event_is_not_re_recorded_when_catalog_sync_is_disabled(self):
        client = TestClient(server.app)
        payload = _build_catalog_updated_payload()

        with patch("server.verify_signature", return_value=True):
            with patch(
                "server.get_webhook_event",
                return_value={
                    "event_id": "catalog-evt-1",
                    "status": server.EVENT_STATUS_IGNORED,
                },
            ):
                with patch("server.create_webhook_event") as mock_create:
                    response = client.post(
                        "/webhook/square",
                        data=json.dumps(payload),
                        headers={"x-square-hmacsha256-signature": "ok"},
                    )

        self.assertEqual(response.status_code, 200)
        mock_create.assert_not_called()
