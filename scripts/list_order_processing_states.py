import json
import sys

from app.order_processing_store import list_order_processing_rows


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.list_order_processing_states "
        "[pending|blocked|failed|applied]"
    )


def main():
    if len(sys.argv) > 2:
        print(_usage())
        return 1

    processing_state = sys.argv[1] if len(sys.argv) == 2 else None
    rows = list_order_processing_rows(processing_state=processing_state)
    print("order_processing:")
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
