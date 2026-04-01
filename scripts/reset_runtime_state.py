import json
from pathlib import Path


RUNTIME_STATE_PATHS = [
    Path("data/order_processing.db"),
    Path("data/webhook_events.db"),
    Path("data/catalog_sync_state.json"),
    Path("data/merchant_auth.db"),
    Path("data/processed_orders.json"),
]


def reset_runtime_state(paths=None):
    removed = []
    missing = []

    for path in paths or RUNTIME_STATE_PATHS:
        if path.exists():
            path.unlink()
            removed.append(str(path))
        else:
            missing.append(str(path))

    return {"removed": removed, "missing": missing}


def main():
    print(json.dumps(reset_runtime_state(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
