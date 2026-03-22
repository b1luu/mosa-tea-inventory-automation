import json
from pathlib import Path


MAP_FILE = Path("data/component_variation_map.json")


def load_component_variation_map():
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return data["component_variation_map"]


def build_variation_to_component_map():
    component_map = load_component_variation_map()
    return {
        variation_id: component_key
        for component_key, variation_id in component_map.items()
    }
