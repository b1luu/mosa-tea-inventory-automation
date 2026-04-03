import json
import sys
import uuid

from square.core.api_error import ApiError

from app.client import create_square_client
from app.json_utils import to_jsonable
from scripts.inspect_order import summarize_order
from testing.live_order_day_profile import (
    build_day_profile_orders,
    build_operational_drill_commands,
    list_day_profiles,
    summarize_day_profile,
)


def _usage():
    return (
        "Usage: ./.venv/bin/python -m testing.run_live_order_day_profile "
        "[--list] [--show-orders] [--show-drill] [--pay] [--offset N] [--limit N] <profile_name>"
    )


def _parse_args(argv):
    if not argv:
        raise ValueError(_usage())

    list_only = "--list" in argv
    show_orders = "--show-orders" in argv
    show_drill = "--show-drill" in argv
    pay_orders = "--pay" in argv

    argv = [
        arg
        for arg in argv
        if arg not in {"--list", "--show-orders", "--show-drill", "--pay"}
    ]

    limit = None
    offset = 0
    if "--limit" in argv:
        limit_index = argv.index("--limit")
        if limit_index + 1 >= len(argv):
            raise ValueError(_usage())
        limit = int(argv[limit_index + 1])
        argv = argv[:limit_index] + argv[limit_index + 2 :]

    if "--offset" in argv:
        offset_index = argv.index("--offset")
        if offset_index + 1 >= len(argv):
            raise ValueError(_usage())
        offset = int(argv[offset_index + 1])
        argv = argv[:offset_index] + argv[offset_index + 2 :]

    if list_only:
        if argv:
            raise ValueError(_usage())
        return list_only, show_orders, show_drill, pay_orders, offset, limit, None

    if len(argv) != 1:
        raise ValueError(_usage())

    return list_only, show_orders, show_drill, pay_orders, offset, limit, argv[0]


def _create_paid_order(client, order_payload, location_id):
    response = client.orders.create(order=order_payload, idempotency_key=str(uuid.uuid4()))
    if not response.order:
        raise RuntimeError("Order creation did not return an order.")

    total_money = response.order.total_money
    if not total_money or total_money.amount is None:
        raise RuntimeError("Created order did not return total_money; cannot create payment.")

    payment_response = client.payments.create(
        source_id="cnon:card-nonce-ok",
        idempotency_key=str(uuid.uuid4()),
        order_id=response.order.id,
        location_id=location_id,
        amount_money={
            "amount": total_money.amount,
            "currency": total_money.currency,
        },
    )
    refreshed_order = client.orders.get(order_id=response.order.id)
    return response.order, payment_response.payment, refreshed_order.order


def main():
    try:
        list_only, show_orders, show_drill, pay_orders, offset, limit, profile_name = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    if list_only:
        print("available_day_profiles:")
        print(json.dumps(list_day_profiles(), indent=2))
        return 0

    try:
        planned_orders = build_day_profile_orders(profile_name, limit=limit, offset=offset)
        summary = summarize_day_profile(profile_name, limit=limit, offset=offset)
    except ValueError as error:
        print(error)
        return 1

    print("profile_summary:")
    print(json.dumps(to_jsonable(summary), indent=2))

    if show_orders:
        print("planned_orders:")
        print(
            json.dumps(
                [
                    {
                        "sequence": planned_order["sequence"],
                        "scenario_name": planned_order["scenario_name"],
                        "drink_count": planned_order["drink_count"],
                        "reference_id": planned_order["order_payload"]["reference_id"],
                    }
                    for planned_order in planned_orders
                ],
                indent=2,
            )
        )

    if show_drill:
        try:
            drill_commands = build_operational_drill_commands(profile_name)
        except ValueError as error:
            print(error)
            return 1

        print("drill_commands:")
        print(json.dumps(drill_commands, indent=2))

    if not pay_orders:
        return 0

    client = create_square_client()
    created_orders = []
    location_id = planned_orders[0]["order_payload"]["location_id"] if planned_orders else None

    for planned_order in planned_orders:
        try:
            created_order, payment, refreshed_order = _create_paid_order(
                client,
                planned_order["order_payload"],
                location_id,
            )
        except (ApiError, RuntimeError) as error:
            print(f"Bulk order creation failed for sequence {planned_order['sequence']}: {error}")
            return 1

        created_orders.append(
            {
                "sequence": planned_order["sequence"],
                "scenario_name": planned_order["scenario_name"],
                "drink_count": planned_order["drink_count"],
                "order_id": created_order.id,
                "reference_id": planned_order["order_payload"]["reference_id"],
                "payment_id": payment.id if payment else None,
                "payment_status": payment.status if payment else None,
                "refreshed_order_state": refreshed_order.state if refreshed_order else None,
            }
        )

    print("created_orders:")
    print(json.dumps(created_orders, indent=2))
    print("last_created_order:")
    print(json.dumps(summarize_order(refreshed_order), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
