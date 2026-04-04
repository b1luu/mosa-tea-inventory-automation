import unittest
from unittest.mock import patch

from app.merchant_store import MerchantContext
from app.webhook_worker import RetryableWebhookJobError, process_webhook_job, replay_order_job


REAL_SUCCESS_JOB = {
    "event_id": "7636f400-d68c-3c80-8f5b-77b8427cab0d",
    "merchant_id": "ML9M9XX0HM717",
    "event_type": "order.updated",
    "order_id": "2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY",
}

MERCHANT_BOUND_JOB = {
    **REAL_SUCCESS_JOB,
    "environment": "sandbox",
    "location_id": "location-1",
}


class WebhookWorkerTests(unittest.TestCase):
    def test_process_webhook_job_claims_pending_order_and_marks_processed(self):
        with patch("app.webhook_worker.claim_order_processing", return_value=True):
            with patch(
                "app.webhook_worker.process_orders",
                return_value={
                    "projected_orders": [{"order_id": REAL_SUCCESS_JOB["order_id"]}],
                    "skipped_orders": [],
                    "skipped_line_items": [],
                    "inventory_response": {"ok": True},
                },
            ) as mock_process:
                with patch("app.webhook_worker.mark_order_applied", return_value=True):
                    with patch(
                        "app.webhook_worker.set_webhook_event_status"
                    ) as mock_status:
                        result = process_webhook_job(REAL_SUCCESS_JOB)

        mock_process.assert_called_once_with(
            ["2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"], apply_changes=True
        )
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "processed"
        )
        self.assertEqual(result, "applied")

    def test_process_webhook_job_marks_blocked_orders_processed(self):
        with patch("app.webhook_worker.claim_order_processing", return_value=True):
            with patch(
                "app.webhook_worker.process_orders",
                return_value={
                    "projected_orders": [{"order_id": REAL_SUCCESS_JOB["order_id"]}],
                    "skipped_orders": [],
                    "skipped_line_items": [{"sold_variation_id": "missing"}],
                    "inventory_response": {
                        "error": "Refusing to apply inventory changes because one or more line items were skipped during projection."
                    },
                },
            ):
                with patch("app.webhook_worker.mark_order_blocked", return_value=True):
                    with patch(
                        "app.webhook_worker.set_webhook_event_status"
                    ) as mock_status:
                        result = process_webhook_job(REAL_SUCCESS_JOB)

        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "processed"
        )
        self.assertEqual(result, "blocked")

    def test_process_webhook_job_returns_failed_for_terminal_failures(self):
        with patch("app.webhook_worker.claim_order_processing", return_value=True):
            with patch(
                "app.webhook_worker.process_orders",
                return_value={
                    "projected_orders": [{"order_id": REAL_SUCCESS_JOB["order_id"]}],
                    "skipped_orders": [],
                    "skipped_line_items": [],
                    "inventory_response": {"error": "Square API error: boom"},
                },
            ):
                with patch("app.webhook_worker.mark_order_failed", return_value=True):
                    with patch(
                        "app.webhook_worker.set_webhook_event_status"
                    ) as mock_status:
                        result = process_webhook_job(REAL_SUCCESS_JOB)

        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "failed"
        )
        self.assertEqual(result, "failed")

    def test_process_webhook_job_noops_when_duplicate_delivery_arrives_after_success(self):
        with patch("app.webhook_worker.claim_order_processing", return_value=False):
            with patch(
                "app.webhook_worker.get_order_processing_state", return_value="applied"
            ):
                with patch("app.webhook_worker.process_orders") as mock_process:
                    with patch(
                        "app.webhook_worker.set_webhook_event_status"
                    ) as mock_status:
                        result = process_webhook_job(REAL_SUCCESS_JOB)

        mock_process.assert_not_called()
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "processed"
        )
        self.assertEqual(result, "applied")

    def test_process_webhook_job_retries_when_order_is_already_processing(self):
        with patch("app.webhook_worker.claim_order_processing", return_value=False):
            with patch(
                "app.webhook_worker.get_order_processing_state", return_value="processing"
            ):
                with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
                    with self.assertRaises(RetryableWebhookJobError):
                        process_webhook_job(REAL_SUCCESS_JOB)

        mock_status.assert_not_called()

    def test_process_webhook_job_releases_claim_on_unexpected_failure(self):
        with patch("app.webhook_worker.claim_order_processing", return_value=True):
            with patch(
                "app.webhook_worker.process_orders", side_effect=RuntimeError("boom")
            ):
                with patch(
                    "app.webhook_worker.release_order_processing_claim", return_value=True
                ) as mock_release:
                    with patch(
                        "app.webhook_worker.set_webhook_event_status"
                    ) as mock_status:
                        with self.assertRaises(RuntimeError):
                            process_webhook_job(REAL_SUCCESS_JOB)

        mock_release.assert_called_once_with("2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY")
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "failed"
        )

    def test_replay_order_job_requeues_failed_orders_before_processing(self):
        with patch("app.webhook_worker.get_order_processing_state", return_value="failed"):
            with patch("app.webhook_worker.requeue_order_processing", return_value=True):
                with patch("app.webhook_worker.claim_order_processing", return_value=True):
                    with patch(
                        "app.webhook_worker.process_orders",
                        return_value={
                            "mode": {"apply": True},
                            "projected_orders": [{"order_id": "order-1"}],
                            "skipped_orders": [],
                            "skipped_line_items": [],
                            "projected_line_items": [],
                            "combined_usage": [],
                            "display_usage": [],
                            "inventory_request": {},
                            "inventory_response": {"ok": True},
                        },
                    ):
                        with patch(
                            "app.webhook_worker.mark_order_applied", return_value=True
                        ):
                            result = replay_order_job("order-1")

        self.assertEqual(result["current_processing_state"], "failed")
        self.assertEqual(result["processing_state_after"], "applied")

    def test_replay_order_job_refuses_applied_orders(self):
        with patch("app.webhook_worker.get_order_processing_state", return_value="applied"):
            with self.assertRaises(RuntimeError):
                replay_order_job("order-1")

    def test_process_webhook_job_marks_failed_when_order_id_is_missing(self):
        with patch("app.webhook_worker.set_webhook_event_status") as mock_status:
            with self.assertRaises(KeyError):
                process_webhook_job(
                    {
                        "event_id": "7636f400-d68c-3c80-8f5b-77b8427cab0d",
                        "merchant_id": "ML9M9XX0HM717",
                        "event_type": "order.updated",
                    }
                )

        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "failed"
        )

    def test_process_webhook_job_uses_merchant_scoped_client_and_binding(self):
        merchant_context = MerchantContext(
            environment="sandbox",
            merchant_id="ML9M9XX0HM717",
            status="active",
            auth_mode="oauth",
            location_id="location-1",
            writes_enabled=True,
            binding_version=2,
            display_name="Default Test Account",
        )
        binding = {"mapping": {"inventory_variation_ids": {"tgy": "LIVE-TGY"}}}

        with patch("app.webhook_worker.claim_order_processing", return_value=True):
            with patch(
                "app.webhook_worker.get_merchant_context",
                return_value=merchant_context,
            ):
                with patch(
                    "app.webhook_worker.get_active_catalog_binding",
                    return_value=binding,
                ):
                    with patch(
                        "app.webhook_worker.create_square_client_for_merchant",
                        return_value="merchant-client",
                    ) as mock_client:
                        with patch(
                            "app.webhook_worker.process_orders",
                            return_value={
                                "projected_orders": [{"order_id": REAL_SUCCESS_JOB["order_id"]}],
                                "skipped_orders": [],
                                "skipped_line_items": [],
                                "inventory_response": {"ok": True},
                            },
                        ) as mock_process:
                            with patch(
                                "app.webhook_worker.mark_order_applied",
                                return_value=True,
                            ):
                                with patch(
                                    "app.webhook_worker.set_webhook_event_status"
                                ):
                                    result = process_webhook_job(MERCHANT_BOUND_JOB)

        mock_client.assert_called_once_with("sandbox", "ML9M9XX0HM717")
        mock_process.assert_called_once_with(
            ["2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"],
            apply_changes=True,
            client="merchant-client",
            binding=binding,
        )
        self.assertEqual(result, "applied")

    def test_process_webhook_job_blocks_when_writes_are_disabled(self):
        merchant_context = MerchantContext(
            environment="sandbox",
            merchant_id="ML9M9XX0HM717",
            status="active",
            auth_mode="oauth",
            location_id="location-1",
            writes_enabled=False,
            binding_version=2,
            display_name="Default Test Account",
        )
        binding = {"mapping": {"inventory_variation_ids": {"tgy": "LIVE-TGY"}}}

        with patch("app.webhook_worker.claim_order_processing", return_value=True):
            with patch(
                "app.webhook_worker.get_merchant_context",
                return_value=merchant_context,
            ):
                with patch(
                    "app.webhook_worker.get_active_catalog_binding",
                    return_value=binding,
                ):
                    with patch(
                        "app.webhook_worker.create_square_client_for_merchant",
                        return_value="merchant-client",
                    ):
                        with patch(
                            "app.webhook_worker.process_orders",
                            return_value={
                                "mode": {"apply": False},
                                "projected_orders": [{"order_id": REAL_SUCCESS_JOB["order_id"]}],
                                "skipped_orders": [],
                                "skipped_line_items": [],
                                "projected_line_items": [],
                                "combined_usage": [],
                                "display_usage": [],
                                "inventory_request": {},
                                "inventory_response": None,
                            },
                        ) as mock_process:
                            with patch(
                                "app.webhook_worker.mark_order_blocked",
                                return_value=True,
                            ):
                                with patch(
                                    "app.webhook_worker.set_webhook_event_status"
                                ) as mock_status:
                                    result = process_webhook_job(MERCHANT_BOUND_JOB)

        mock_process.assert_called_once_with(
            ["2bmc3h9wsfHfMfEwBIQm0ZQNO9FZY"],
            apply_changes=False,
            client="merchant-client",
            binding=binding,
        )
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "processed"
        )
        self.assertEqual(result, "blocked")

    def test_process_webhook_job_blocks_when_binding_is_missing(self):
        merchant_context = MerchantContext(
            environment="sandbox",
            merchant_id="ML9M9XX0HM717",
            status="active",
            auth_mode="oauth",
            location_id="location-1",
            writes_enabled=True,
            binding_version=None,
            display_name="Default Test Account",
        )

        with patch("app.webhook_worker.claim_order_processing", return_value=True):
            with patch(
                "app.webhook_worker.get_merchant_context",
                return_value=merchant_context,
            ):
                with patch(
                    "app.webhook_worker.get_active_catalog_binding",
                    return_value=None,
                ):
                    with patch(
                        "app.webhook_worker.create_square_client_for_merchant"
                    ) as mock_client:
                        with patch("app.webhook_worker.process_orders") as mock_process:
                            with patch(
                                "app.webhook_worker.mark_order_blocked",
                                return_value=True,
                            ):
                                with patch(
                                    "app.webhook_worker.set_webhook_event_status"
                                ) as mock_status:
                                    result = process_webhook_job(MERCHANT_BOUND_JOB)

        mock_client.assert_not_called()
        mock_process.assert_not_called()
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "processed"
        )
        self.assertEqual(result, "blocked")

    def test_process_webhook_job_blocks_when_merchant_is_revoked(self):
        merchant_context = MerchantContext(
            environment="sandbox",
            merchant_id="ML9M9XX0HM717",
            status="revoked",
            auth_mode="oauth",
            location_id="location-1",
            writes_enabled=False,
            binding_version=2,
            display_name="Default Test Account",
        )

        with patch("app.webhook_worker.claim_order_processing", return_value=True):
            with patch(
                "app.webhook_worker.get_merchant_context",
                return_value=merchant_context,
            ):
                with patch(
                    "app.webhook_worker.get_active_catalog_binding"
                ) as mock_binding:
                    with patch(
                        "app.webhook_worker.create_square_client_for_merchant"
                    ) as mock_client:
                        with patch("app.webhook_worker.process_orders") as mock_process:
                            with patch(
                                "app.webhook_worker.mark_order_blocked",
                                return_value=True,
                            ):
                                with patch(
                                    "app.webhook_worker.set_webhook_event_status"
                                ) as mock_status:
                                    result = process_webhook_job(MERCHANT_BOUND_JOB)

        mock_binding.assert_called_once_with("sandbox", "ML9M9XX0HM717", "location-1")
        mock_client.assert_not_called()
        mock_process.assert_not_called()
        mock_status.assert_called_once_with(
            "7636f400-d68c-3c80-8f5b-77b8427cab0d", "processed"
        )
        self.assertEqual(result, "blocked")
