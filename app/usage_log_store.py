"""Per-order ingredient usage, recorded by the worker when an order is applied.

One row per (order, ingredient). This is the demand record for ingredients
that are never recounted from the sheet (milk, frozen fruit) and the only
record for log-only ingredients that have no Square item (oat milk).

Rows are keyed by ``environment#merchant#location#inventory_key`` and sorted by
``<sold_at>#<order_id>``, so a time-range query per ingredient is one read and a
retried order overwrites its own rows.
"""

from decimal import Decimal

from app import usage_log_db, usage_log_dynamodb
from app.config import get_usage_log_store_mode


def _get_store_backend():
    store_mode = get_usage_log_store_mode()
    if store_mode == "sqlite":
        return usage_log_db
    if store_mode == "dynamodb":
        return usage_log_dynamodb
    raise ValueError(f"Unsupported usage log store mode: {store_mode}")


def build_usage_key(environment, merchant_id, location_id, inventory_key):
    return f"{environment}#{merchant_id}#{location_id}#{inventory_key}"


def record_order_usage(environment, merchant_id, location_id, order_id, sold_at, usage):
    """Record one order's per-ingredient usage (the projected usage entries for that order)."""
    totals = {}
    for entry in usage:
        inventory_key = entry["inventory_key"]
        amount, unit = totals.get(inventory_key, (Decimal("0"), entry["inventory_unit"]))
        totals[inventory_key] = (amount + Decimal(str(entry["total_amount"])), unit)

    rows = [
        {
            "usage_key": build_usage_key(environment, merchant_id, location_id, inventory_key),
            "sold_at_order_id": f"{sold_at}#{order_id}",
            "environment": environment,
            "merchant_id": merchant_id,
            "location_id": location_id,
            "inventory_key": inventory_key,
            "order_id": order_id,
            "sold_at": sold_at,
            "amount": str(amount),
            "unit": unit,
        }
        for inventory_key, (amount, unit) in sorted(totals.items())
        if amount > 0
    ]
    if not rows:
        return rows
    if not sold_at:
        raise ValueError(f"Order '{order_id}' has no sale time; cannot record usage.")
    _get_store_backend().put_usage_rows(rows)
    return rows


def list_usage(environment, merchant_id, location_id, inventory_key, start_sold_at, end_sold_at):
    """Rows for one ingredient with ``start_sold_at <= sold_at < end_sold_at`` (ISO strings)."""
    return _get_store_backend().query_usage_rows(
        build_usage_key(environment, merchant_id, location_id, inventory_key),
        start_sold_at,
        end_sold_at,
    )
