import unittest
from unittest.mock import patch

from app.manual_count_sync import sync_manual_inventory_count
from app.order_inventory_projection import load_inventory_item_map


class _FakeCount:
    def __init__(self, state, quantity, calculated_at="2026-04-06T12:00:00Z"):
        self.state = state
        self.quantity = quantity
        self.calculated_at = calculated_at


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self, mode="json"):
        return self._payload


class _FakeInventoryClient:
    def __init__(self, counts):
        self._counts = counts
        self.applied_requests = []

    def batch_get_counts(self, **kwargs):
        return list(self._counts)

    def batch_create_changes(self, **kwargs):
        self.applied_requests.append(kwargs)
        return _FakeResponse({"changes_applied": True, "request": kwargs})


class _FakeClient:
    def __init__(self, counts):
        self.inventory = _FakeInventoryClient(counts)


class ManualCountSyncTests(unittest.TestCase):
    def test_dry_run_builds_physical_count_request_for_black_tea(self):
        client = _FakeClient(
            [
                _FakeCount("IN_STOCK", "80"),
                _FakeCount("WASTE", "5"),
            ]
        )
        with (
            patch(
                "app.manual_count_sync.get_merchant_context",
                return_value=type(
                    "MerchantContext",
                    (),
                    {"status": "active", "writes_enabled": True},
                )(),
            ),
            patch(
                "app.manual_count_sync.get_active_catalog_binding",
                return_value={
                    "mapping": {
                        "inventory_variation_ids": {
                            "black_tea": "VAR-BLACK-TEA",
                        }
                    }
                },
            ),
            patch(
                "app.manual_count_sync.create_square_client_for_merchant",
                return_value=client,
            ),
        ):
            result = sync_manual_inventory_count(
                environment="sandbox",
                merchant_id="merchant-1",
                location_id="LOC-1",
                inventory_key="black_tea",
                counted_quantity="75",
                counted_unit="bag",
                apply_changes=False,
                source_reference="sheet:Sheet1!D2",
            )

        self.assertFalse(result["mode"]["apply"])
        self.assertEqual(result["catalog_object_id"], "VAR-BLACK-TEA")
        self.assertEqual(str(result["current_square_count"]["in_stock_quantity"]), "80")
        self.assertEqual(str(result["delta"]["in_stock_quantity"]), "-5.00000")
        self.assertEqual(result["inventory_request"]["changes"][0]["type"], "PHYSICAL_COUNT")
        self.assertEqual(
            result["inventory_request"]["changes"][0]["physical_count"]["quantity"],
            "75.00000",
        )
        self.assertNotIn(
            "catalog_object_type",
            result["inventory_request"]["changes"][0]["physical_count"],
        )
        self.assertIsNone(result["inventory_response"])
        self.assertEqual(client.inventory.applied_requests, [])

    def test_apply_calls_square_for_physical_count_sync(self):
        client = _FakeClient(
            [
                _FakeCount("IN_STOCK", "80"),
                _FakeCount("WASTE", "5"),
            ]
        )
        with (
            patch(
                "app.manual_count_sync.get_merchant_context",
                return_value=type(
                    "MerchantContext",
                    (),
                    {"status": "active", "writes_enabled": True},
                )(),
            ),
            patch(
                "app.manual_count_sync.get_active_catalog_binding",
                return_value={
                    "mapping": {
                        "inventory_variation_ids": {
                            "black_tea": "VAR-BLACK-TEA",
                        }
                    }
                },
            ),
            patch(
                "app.manual_count_sync.create_square_client_for_merchant",
                return_value=client,
            ),
        ):
            result = sync_manual_inventory_count(
                environment="sandbox",
                merchant_id="merchant-1",
                location_id="LOC-1",
                inventory_key="black_tea",
                counted_quantity="75",
                counted_unit="bag",
                apply_changes=True,
                source_reference="sheet:Sheet1!D2",
            )

        self.assertTrue(result["mode"]["apply"])
        self.assertEqual(len(client.inventory.applied_requests), 1)
        self.assertTrue(result["inventory_response"]["changes_applied"])

    def test_apply_requires_writes_enabled(self):
        client = _FakeClient([_FakeCount("IN_STOCK", "80")])
        with (
            patch(
                "app.manual_count_sync.get_merchant_context",
                return_value=type(
                    "MerchantContext",
                    (),
                    {"status": "active", "writes_enabled": False},
                )(),
            ),
            patch(
                "app.manual_count_sync.get_active_catalog_binding",
                return_value={
                    "mapping": {
                        "inventory_variation_ids": {
                            "black_tea": "VAR-BLACK-TEA",
                        }
                    }
                },
            ),
            patch(
                "app.manual_count_sync.create_square_client_for_merchant",
                return_value=client,
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Inventory writes are disabled pending owner approval.",
            ):
                sync_manual_inventory_count(
                    environment="sandbox",
                    merchant_id="merchant-1",
                    location_id="LOC-1",
                    inventory_key="black_tea",
                    counted_quantity="75",
                    counted_unit="bag",
                    apply_changes=True,
                )

    def test_dry_run_accepts_all_supported_tea_inventory_keys(self):
        tea_keys = [
            "black_tea",
            "green_tea",
            "tgy",
            "4s",
            "barley",
            "buckwheat",
            "genmai",
            "boba",
            "non_dairy_creamer",
            "lychee_jelly",
            "cream_foam_powder",
            "brown_sugar",
            "tj_powder",
            "hk_powder",
        ]

        for inventory_key in tea_keys:
            client = _FakeClient([_FakeCount("IN_STOCK", "80")])
            counted_unit = load_inventory_item_map()[inventory_key]["stock_unit"]
            with self.subTest(inventory_key=inventory_key):
                with (
                    patch(
                        "app.manual_count_sync.get_merchant_context",
                        return_value=type(
                            "MerchantContext",
                            (),
                            {"status": "active", "writes_enabled": True},
                        )(),
                    ),
                    patch(
                        "app.manual_count_sync.get_active_catalog_binding",
                        return_value={
                            "mapping": {
                                "inventory_variation_ids": {
                                    inventory_key: f"VAR-{inventory_key.upper()}",
                                }
                            }
                        },
                    ),
                    patch(
                        "app.manual_count_sync.create_square_client_for_merchant",
                        return_value=client,
                    ),
                ):
                    result = sync_manual_inventory_count(
                        environment="sandbox",
                        merchant_id="merchant-1",
                        location_id="LOC-1",
                        inventory_key=inventory_key,
                        counted_quantity="75",
                        counted_unit=counted_unit,
                        apply_changes=False,
                    )

                self.assertEqual(result["inventory_key"], inventory_key)
                self.assertEqual(
                    str(result["inventory_request"]["changes"][0]["physical_count"]["quantity"]),
                    "75.00000",
                )


if __name__ == "__main__":
    unittest.main()
