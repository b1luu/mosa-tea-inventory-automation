import json
from datetime import datetime, timezone
from pathlib import Path


STATE_FILE = Path("data/catalog_sync_state.json")


def _utc_now_rfc3339():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_state_dir():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _write_state(last_synced_at):
    _ensure_state_dir()
    STATE_FILE.write_text(
        json.dumps({"last_synced_at": last_synced_at}, indent=2) + "\n",
        encoding="utf-8",
    )


def get_or_create_last_synced_at():
    if not STATE_FILE.exists():
        last_synced_at = _utc_now_rfc3339()
        _write_state(last_synced_at)
        return last_synced_at

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return state["last_synced_at"]


def update_last_synced_at(last_synced_at):
    _write_state(last_synced_at)
