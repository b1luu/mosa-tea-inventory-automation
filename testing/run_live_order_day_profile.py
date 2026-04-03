import json
import sys
import time
import uuid

from square.core.api_error import ApiError

from app.client import create_square_client
from app.json_utils import to_jsonable
from scripts.inspect_order import summarize_order
from testing.live_order_day_profile import (
    build_day_profile_orders,
    build_dispatch_schedule,
    build_operational_drill_commands,
    list_day_profiles,
    summarize_day_profile,
)


class ScheduleRunInterrupted(Exception):
    def __init__(self, completed_batches):
        super().__init__("Scheduled run interrupted.")
        self.completed_batches = completed_batches


def _usage():
    return (
        "Usage: ./.venv/bin/python -m testing.run_live_order_day_profile "
        "[--list] [--show-orders] [--show-drill] [--show-schedule] [--run-schedule] "
        "[--pay] [--offset N] [--limit N] [--schedule-scale N] [--per-order-delay-seconds N] <profile_name>"
    )


def _parse_args(argv):
    if not argv:
        raise ValueError(_usage())

    list_only = "--list" in argv
    show_orders = "--show-orders" in argv
    show_drill = "--show-drill" in argv
    show_schedule = "--show-schedule" in argv
    run_schedule = "--run-schedule" in argv
    pay_orders = "--pay" in argv

    argv = [
        arg
        for arg in argv
        if arg
        not in {
            "--list",
            "--show-orders",
            "--show-drill",
            "--show-schedule",
            "--run-schedule",
            "--pay",
        }
    ]

    limit = None
    offset = 0
    schedule_scale = 1
    per_order_delay_seconds = 0
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

    if "--schedule-scale" in argv:
        scale_index = argv.index("--schedule-scale")
        if scale_index + 1 >= len(argv):
            raise ValueError(_usage())
        schedule_scale = float(argv[scale_index + 1])
        argv = argv[:scale_index] + argv[scale_index + 2 :]

    if "--per-order-delay-seconds" in argv:
        delay_index = argv.index("--per-order-delay-seconds")
        if delay_index + 1 >= len(argv):
            raise ValueError(_usage())
        per_order_delay_seconds = float(argv[delay_index + 1])
        argv = argv[:delay_index] + argv[delay_index + 2 :]

    if list_only:
        if argv:
            raise ValueError(_usage())
        return (
            list_only,
            show_orders,
            show_drill,
            show_schedule,
            run_schedule,
            pay_orders,
            offset,
            limit,
            schedule_scale,
            per_order_delay_seconds,
            None,
        )

    if len(argv) != 1:
        raise ValueError(_usage())

    return (
        list_only,
        show_orders,
        show_drill,
        show_schedule,
        run_schedule,
        pay_orders,
        offset,
        limit,
        schedule_scale,
        per_order_delay_seconds,
        argv[0],
    )


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


def _execute_paid_orders(planned_orders, per_order_delay_seconds=0):
    if not planned_orders:
        return []

    client = create_square_client()
    location_id = planned_orders[0]["order_payload"]["location_id"]
    created_orders = []

    for index, planned_order in enumerate(planned_orders):
        created_order, payment, refreshed_order = _create_paid_order(
            client,
            planned_order["order_payload"],
            location_id,
        )
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
        if per_order_delay_seconds > 0 and index < len(planned_orders) - 1:
            time.sleep(per_order_delay_seconds)

    return created_orders


def _run_dispatch_schedule(profile_name, schedule_scale, per_order_delay_seconds):
    schedule = build_dispatch_schedule(profile_name, schedule_scale=schedule_scale)
    completed_batches = []

    try:
        for batch in schedule:
            sleep_before_seconds = float(batch["sleep_before_seconds"])
            if sleep_before_seconds > 0:
                time.sleep(sleep_before_seconds)

            planned_orders = build_day_profile_orders(
                profile_name,
                offset=batch["offset"],
                limit=batch["limit"],
            )
            created_orders = _execute_paid_orders(
                planned_orders,
                per_order_delay_seconds=per_order_delay_seconds,
            )
            completed_batches.append(
                {
                    "batch_number": batch["batch_number"],
                    "offset": batch["offset"],
                    "limit": batch["limit"],
                    "dispatch_offset_minutes": batch["dispatch_offset_minutes"],
                    "created_order_count": len(created_orders),
                    "created_orders": created_orders,
                }
            )
    except KeyboardInterrupt as error:
        raise ScheduleRunInterrupted(completed_batches) from error

    return completed_batches


def main():
    try:
        (
            list_only,
            show_orders,
            show_drill,
            show_schedule,
            run_schedule,
            pay_orders,
            offset,
            limit,
            schedule_scale,
            per_order_delay_seconds,
            profile_name,
        ) = _parse_args(sys.argv[1:])
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

    if show_schedule or run_schedule:
        try:
            schedule = build_dispatch_schedule(
                profile_name,
                schedule_scale=schedule_scale,
            )
        except ValueError as error:
            print(error)
            return 1

        print("dispatch_schedule:")
        print(json.dumps(schedule, indent=2))

    if run_schedule:
        if not pay_orders:
            print("--run-schedule requires --pay.")
            return 1
        if offset != 0 or limit is not None:
            print("--run-schedule cannot be combined with --offset/--limit.")
            return 1

        try:
            completed_batches = _run_dispatch_schedule(
                profile_name,
                schedule_scale=schedule_scale,
                per_order_delay_seconds=per_order_delay_seconds,
            )
        except ScheduleRunInterrupted as error:
            print("schedule_run_interrupted:")
            print(
                json.dumps(
                    {
                        "profile_name": profile_name,
                        "reason": "KeyboardInterrupt",
                        "completed_batches": error.completed_batches,
                    },
                    indent=2,
                )
            )
            return 130
        except (ApiError, RuntimeError) as error:
            print(f"Scheduled run failed: {error}")
            return 1

        print("completed_batches:")
        print(json.dumps(completed_batches, indent=2))
        return 0

    if not pay_orders:
        return 0

    try:
        created_orders = _execute_paid_orders(
            planned_orders,
            per_order_delay_seconds=per_order_delay_seconds,
        )
    except (ApiError, RuntimeError) as error:
        print(f"Bulk order creation failed: {error}")
        return 1

    print("created_orders:")
    print(json.dumps(created_orders, indent=2))
    if created_orders:
        last_order_id = created_orders[-1]["order_id"]
        try:
            client = create_square_client()
            refreshed_order = client.orders.get(order_id=last_order_id).order
        except ApiError as error:
            print(f"Square API error: {error}")
            return 1

        print("last_created_order:")
        print(json.dumps(summarize_order(refreshed_order), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
