import unittest

from testing.create_live_test_order import (
    MAX_REFERENCE_ID_LENGTH,
    _build_order_payload,
    _build_reference_id,
)


class CreateLiveTestOrderTests(unittest.TestCase):
    def test_build_reference_id_keeps_short_names_intact(self):
        self.assertEqual(
            _build_reference_id("signature_black_milk_tea"),
            "testing:signature_black_milk_tea",
        )

    def test_build_reference_id_truncates_long_names_to_square_limit(self):
        reference_id = _build_reference_id(
            "roasted_buckwheat_barley_milk_tea_100_sugar"
        )

        self.assertLessEqual(len(reference_id), MAX_REFERENCE_ID_LENGTH)
        self.assertTrue(reference_id.startswith("testing:"))

    def test_build_order_payload_uses_bounded_reference_id(self):
        payload = _build_order_payload(
            "LB1MECVA7EZ8Z",
            "roasted_buckwheat_barley_milk_tea_100_sugar",
            {
                "line_items": [
                    {
                        "catalog_object_id": "UMBGTNZ3VXRWVFZQ3D2UESYF",
                        "quantity": "1",
                        "modifiers": [
                            {
                                "catalog_object_id": "VEDNAO6LH5WQET6TQTJGSPOB",
                                "quantity": "1",
                            }
                        ],
                    }
                ]
            },
        )

        self.assertLessEqual(
            len(payload["reference_id"]),
            MAX_REFERENCE_ID_LENGTH,
        )
        self.assertEqual(
            payload["line_items"][0]["catalog_object_id"],
            "UMBGTNZ3VXRWVFZQ3D2UESYF",
        )


if __name__ == "__main__":
    unittest.main()
