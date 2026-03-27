import json
import sys
from pathlib import Path

from square.core.api_error import ApiError

from app.client import create_square_client
from scripts.inspect_order import summarize_order


FIXTURE_DIR = Path("testing/fixtures/orders")


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: ./.venv/bin/python -m testing.export_order_fixture "
            "<order_id> <fixture_name>"
        )
        return 1

    order_id = sys.argv[1]
    fixture_name = sys.argv[2]
    client = create_square_client()

    try:
        response = client.orders.get(order_id=order_id)
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    if not response.order:
        print(f"Order not found: {order_id}")
        return 1

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    fixture_path = FIXTURE_DIR / f"{fixture_name}.json"
    fixture_path.write_text(
        json.dumps(summarize_order(response.order), indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote fixture: {fixture_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
