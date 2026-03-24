import json
from pathlib import Path


STATE_FILE = Path("data/processed_orders.json")


def _ensure_state_dir():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _write_state(processed_order_ids):
    _ensure_state_dir()
    STATE_FILE.write_text(
        json.dumps({"processed_order_ids": sorted(processed_order_ids)}, indent=2) + "\n",
        encoding="utf-8",
    )


def load_processed_order_ids():
    if not STATE_FILE.exists():
        return set()

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return set(state.get("processed_order_ids", []))


def mark_orders_processed(order_ids):
    processed_order_ids = load_processed_order_ids()
    processed_order_ids.update(order_ids)
    _write_state(processed_order_ids)
