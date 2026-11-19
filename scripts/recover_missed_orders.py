"""Recover paid orders whose webhooks never reached the ingress Lambda.

For every order created since --since that commits inventory (COMPLETED, or
OPEN and paid in full; see app/order_commit_rules.py) and has no
order_processing row, reserve a pending row exactly as webhook ingress does and
queue a job for the deployed worker. Paid-but-OPEN orders get the same
PAID_ORDER_HOLD_SECONDS delay ingress gives them.

Orders that already have a row are never re-queued. Applied, blocked and failed
rows are finished. A pending row may be one ingress just reserved and is
holding for 15 minutes; re-queuing it would skip the hold. Pending rows are
printed for a manual look instead.

The order search uses created_at, the same window as the daily reconciliation,
so the "would queue" list can be checked against the reconciliation email.

Dry run by default; pass --apply to reserve and queue. Pass --order-id to
limit a run to one order (still within --since, and through every check
above), for the first run in production. Production requires
ORDER_PROCESSING_STORE_MODE=dynamodb and MERCHANT_STORE_MODE=dynamodb, so the
script reads the prod stores and token, not local SQLite files. Every run
starts by printing its setup, including the SQS queue URL.
"""

import sys

from app.client import create_square_client_for_merchant
from app.config import (
    get_merchant_store_mode,
    get_order_processing_store_mode,
    get_webhook_job_queue_url,
)
from app.order_commit_rules import PAID_ORDER_HOLD_SECONDS, is_committable_order
from app.order_processing_db import PROCESSING_STATE_PENDING
from app.order_processing_store import (
    clear_order_processing_reservation,
    get_order_processing_state,
    reserve_order_processing,
)
from app.sqs_dispatcher import dispatch_webhook_job_to_sqs


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.recover_missed_orders "
        "--environment sandbox|production --merchant-id MERCHANT_ID "
        "--location-id LOCATION_ID --since RFC3339_TIMESTAMP "
        "[--order-id ORDER_ID] [--apply]"
    )


def _parse_args(argv):
    values = {}
    apply_changes = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--apply":
            apply_changes = True
        elif arg in {"--environment", "--merchant-id", "--location-id", "--since", "--order-id"}:
            i += 1
            values[arg] = argv[i].strip()
        else:
            raise ValueError(f"Unknown argument: {arg}")
        i += 1

    environment = values.get("--environment", "").lower()
    merchant_id = values.get("--merchant-id")
    location_id = values.get("--location-id")
    since = values.get("--since")
    if environment not in {"sandbox", "production"} or not (
        merchant_id and location_id and since
    ):
        raise ValueError("Missing required arguments.")

    return environment, merchant_id, location_id, since, values.get("--order-id"), apply_changes


def _check_store_mode(environment):
    """Refuse to run against production with a local SQLite store.

    With sqlite order processing, every prod order looks unprocessed and
    --apply would queue all of them. With a sqlite merchant store, the Square
    token comes from the local database instead of prod.
    """
    if environment != "production":
        return
    wrong = [
        name
        for name, mode in (
            ("ORDER_PROCESSING_STORE_MODE", get_order_processing_store_mode()),
            ("MERCHANT_STORE_MODE", get_merchant_store_mode()),
        )
        if mode != "dynamodb"
    ]
    if wrong:
        raise ValueError(
            "Refusing to run against production: set "
            + " and ".join(f"{name}=dynamodb" for name in wrong)
            + " so the script reads the prod tables."
        )


def _describe_setup(environment, merchant_id, location_id, since, order_id, apply_changes):
    try:
        queue_url = get_webhook_job_queue_url()
    except ValueError:
        queue_url = "(WEBHOOK_JOB_QUEUE_URL not set)"
    return [
        f"environment:            {environment}",
        f"merchant / location:    {merchant_id} / {location_id}",
        f"since:                  {since}",
        f"order id:               {order_id or '(all)'}",
        f"order processing store: {get_order_processing_store_mode()}",
        f"merchant store:         {get_merchant_store_mode()}",
        f"queue url:              {queue_url}",
        f"mode:                   {'APPLY' if apply_changes else 'dry run'}",
    ]


def _only_order(orders, order_id):
    if not order_id:
        return orders
    return [order for order in orders if order.id == order_id]


def _search_orders_created_since(client, location_id, since):
    orders = []
    cursor = None
    while True:
        response = client.orders.search(
            location_ids=[location_id],
            cursor=cursor,
            limit=500,
            query={
                "filter": {"date_time_filter": {"created_at": {"start_at": since}}},
                "sort": {"sort_field": "CREATED_AT", "sort_order": "ASC"},
            },
        )
        orders.extend(response.orders or [])
        cursor = response.cursor
        if not cursor:
            return orders


def _build_job(order, *, merchant_id, environment, location_id):
    # The worker needs all three to resolve the merchant and binding, and
    # replay_order_job rebuilds its job from the same fields on the row.
    job = {
        "merchant_id": merchant_id,
        "environment": environment,
        "event_type": "order.updated",
        "order_id": order.id,
        "location_id": location_id,
    }
    if getattr(order, "state", None) != "COMPLETED":
        job["hold_seconds"] = PAID_ORDER_HOLD_SECONDS
    return job


def recover(
    orders,
    *,
    merchant_id,
    environment,
    default_location_id,
    apply_changes,
    out=None,
):
    out = out or print
    summary = {"committable": 0, "missed": 0, "queued": 0, "pending": 0, "dispatch_failed": 0}

    for order in orders:
        if not is_committable_order(order):
            continue
        summary["committable"] += 1

        current_state = get_order_processing_state(order.id)
        if current_state == PROCESSING_STATE_PENDING:
            summary["pending"] += 1
            out(f"already pending, check by hand  {order.created_at}  {order.id}")
            continue
        if current_state is not None:
            continue

        summary["missed"] += 1
        location_id = getattr(order, "location_id", None) or default_location_id
        job = _build_job(
            order,
            merchant_id=merchant_id,
            environment=environment,
            location_id=location_id,
        )
        if not apply_changes:
            out(f"would queue  {order.state}  {order.created_at}  {order.id}")
            continue

        reserved = reserve_order_processing(
            order.id,
            merchant_id=merchant_id,
            environment=environment,
            location_id=location_id,
        )
        if not reserved:
            out(f"skipped (reserved meanwhile)  {order.created_at}  {order.id}")
            continue

        try:
            dispatch_webhook_job_to_sqs(job)
        except Exception as exc:
            # Same as ingress: drop the reservation so a rerun picks it up.
            clear_order_processing_reservation(order.id)
            summary["dispatch_failed"] += 1
            out(f"dispatch failed, reservation cleared  {order.id}  {exc}")
            continue

        summary["queued"] += 1
        out(f"queued  {order.state}  {order.created_at}  {order.id}")

    return summary


def main():
    try:
        environment, merchant_id, location_id, since, order_id, apply_changes = _parse_args(
            sys.argv[1:]
        )
    except (ValueError, IndexError):
        print(_usage())
        return 1

    try:
        for line in _describe_setup(
            environment, merchant_id, location_id, since, order_id, apply_changes
        ):
            print(line)
        _check_store_mode(environment)
    except ValueError as exc:
        print(exc)
        return 1

    client = create_square_client_for_merchant(environment, merchant_id)
    orders = _only_order(_search_orders_created_since(client, location_id, since), order_id)
    if order_id and not orders:
        print(f"order {order_id} not found at {location_id} created since {since}")
        return 1
    summary = recover(
        orders,
        merchant_id=merchant_id,
        environment=environment,
        default_location_id=location_id,
        apply_changes=apply_changes,
    )

    print(
        f"orders created since {since}: {len(orders)} | "
        f"paid: {summary['committable']} | "
        f"without a processing row: {summary['missed']} | "
        f"already pending: {summary['pending']} | "
        f"queued: {summary['queued']} | "
        f"dispatch failed: {summary['dispatch_failed']} | "
        f"mode: {'apply' if apply_changes else 'dry run'}"
    )
    return 1 if summary["dispatch_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
