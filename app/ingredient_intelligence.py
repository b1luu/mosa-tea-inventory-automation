import json
from pathlib import Path


INGREDIENT_INTELLIGENCE_FILE = Path("data/ingredient_intelligence_template.json")


def load_ingredient_intelligence():
    return json.loads(INGREDIENT_INTELLIGENCE_FILE.read_text(encoding="utf-8"))


def get_component_map():
    data = load_ingredient_intelligence()
    return data.get("components", {})


def get_drink_map():
    data = load_ingredient_intelligence()
    return data.get("drinks", {})
