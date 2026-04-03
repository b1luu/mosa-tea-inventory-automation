import json
import sys

from square.core.api_error import ApiError

from app.client import create_square_client
from app.json_utils import to_jsonable
from testing.order_projection_utils import (
    load_fixture_order,
    load_scenario_order,
    project_order_summary,
    summarize_live_order,
)


def _usage():
    return (
        "Usage: ./.venv/bin/python -m testing.inspect_order_math "
        "(--fixture <fixture_name> | --scenario <scenario_name> | --order-id <order_id>)"
    )


def _parse_args(argv):
    if len(argv) != 2:
        raise ValueError(_usage())

    flag, value = argv
    if flag not in {"--fixture", "--scenario", "--order-id"}:
        raise ValueError(_usage())

    return flag, value


def _load_source(flag, value):
    if flag == "--fixture":
        return {
            "source": {"kind": "fixture", "name": value},
            "order": load_fixture_order(value),
        }

    if flag == "--scenario":
        return {
            "source": {"kind": "scenario", "name": value},
            "order": load_scenario_order(value),
        }

    client = create_square_client()
    try:
        response = client.orders.get(order_id=value)
    except ApiError as error:
        raise ValueError(f"Square API error: {error}") from error

    if not response.order:
        raise ValueError(f"Order not found: {value}")

    return {
        "source": {"kind": "live_order", "name": value},
        "order": summarize_live_order(response.order),
    }


def main():
    try:
        flag, value = _parse_args(sys.argv[1:])
        payload = _load_source(flag, value)
    except ValueError as error:
        print(error)
        return 1

    projected_line_items, combined_usage = project_order_summary(payload["order"])

    print("source:")
    print(json.dumps(payload["source"], indent=2))
    print("order:")
    print(json.dumps(to_jsonable(payload["order"]), indent=2))
    print("projected_line_items:")
    print(json.dumps(to_jsonable(projected_line_items), indent=2))
    print("combined_usage:")
    print(json.dumps(to_jsonable(combined_usage), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
