import unittest
from unittest.mock import patch

from app import order_inventory_projection


class OrderInventoryProjectionCacheTests(unittest.TestCase):
    def setUp(self):
        order_inventory_projection.clear_static_config_cache()

    def tearDown(self):
        order_inventory_projection.clear_static_config_cache()

    def test_recipe_map_reads_from_disk_once_when_cached(self):
        with patch(
            "app.order_inventory_projection.Path.read_text",
            return_value='{"sold_variation_recipes": {}}',
        ) as mock_read:
            order_inventory_projection.load_recipe_map()
            order_inventory_projection.load_recipe_map()

        self.assertEqual(mock_read.call_count, 1)

    def test_clear_static_config_cache_forces_reload(self):
        with patch(
            "app.order_inventory_projection.Path.read_text",
            return_value='{"inventory_items": {}}',
        ) as mock_read:
            order_inventory_projection.load_inventory_item_map()
            order_inventory_projection.clear_static_config_cache()
            order_inventory_projection.load_inventory_item_map()

        self.assertEqual(mock_read.call_count, 2)
