"""Daily order reconciliation: did every sale Square recorded get deducted?

Compares Square's orders for one shop day (midnight to midnight, California)
with the order processing store, and sorts each order into one bucket. See
docs/daily-order-reconciliation-design.md.

``classify`` is pure. ``explain`` dry-runs the worker's projection to say why
an order was not deducted. ``run_daily_reconciliation`` and
``run_weekly_summary`` load everything for one merchant.
"""

from collections import Counter
from datetime import timedelta

from app.client import create_square_client_for_merchant
from app.merchant_store import get_active_catalog_binding
from app.order_commit_rules import is_cancelled_order, is_committable_order
from app.order_processing_db import (
    PROCESSING_STATE_APPLIED,
    PROCESSING_STATE_BLOCKED,
    PROCESSING_STATE_FAILED,
    PROCESSING_STATE_PENDING,
    PROCESSING_STATE_PROCESSING,
)
from app.order_processing_store import get_order_processing_record
from app.order_processor import process_orders
from app.shop_time import day_window, local_day_of, to_local

# Buckets that mean a sale was not deducted correctly; any of these emails.
PROBLEM_BUCKETS = ("blocked", "failed", "stuck", "missed", "reversed")
OK_BUCKETS = ("applied", "not_a_sale")
# Paid orders the commit rule skips, grouped by channel: this many in one day
# from one channel is a pattern worth an email (the Kiosk gap looked like this).
PAID_NOT_DEDUCTIBLE_PATTERN_THRESHOLD = 3

BUCKET_TITLES = {
    "blocked": "BLOCKED",
    "failed": "FAILED",
    "stuck": "STUCK (never finished processing)",
    "missed": "MISSED (no processing record)",
    "reversed": "REVERSED AFTER DEDUCTION (cancelled after we deducted)",
}


def _source(order):
    return getattr(getattr(order, "source", None), "name", None) or "Point of Sale"


def _is_paid(order):
    if not getattr(order, "tenders", None):
        return False
    due = getattr(order, "net_amount_due_money", None)
    return due is None or (getattr(due, "amount", 0) or 0) == 0


def _describe_items(order):
    parts = []
    for line_item in getattr(order, "line_items", None) or []:
        quantity = getattr(line_item, "quantity", "1")
        modifiers = ", ".join(
            modifier.name for modifier in (getattr(line_item, "modifiers", None) or []) if modifier.name
        )
        parts.append(f"{quantity} x {line_item.name}" + (f" ({modifiers})" if modifiers else ""))
    return "; ".join(parts)


def _item_count(order):
    return sum(
        int(float(getattr(line_item, "quantity", "1") or 1))
        for line_item in getattr(order, "line_items", None) or []
    )


def _entry(order, processing_state):
    return {
        "order_id": order.id,
        "created_at": order.created_at,
        "source": _source(order),
        "state": order.state,
        "processing_state": processing_state,
        "items": _describe_items(order),
        "item_count": _item_count(order),
    }


def classify(orders, records_by_order_id):
    """Sort orders into buckets. ``records_by_order_id`` maps order id to a processing record or None."""
    buckets = {name: [] for name in PROBLEM_BUCKETS + OK_BUCKETS + ("paid_not_deductible",)}

    for order in orders:
        record = records_by_order_id.get(order.id) or {}
        state = record.get("processing_state")
        entry = _entry(order, state)

        if is_committable_order(order):
            if state == PROCESSING_STATE_APPLIED:
                bucket = "applied"
            elif state == PROCESSING_STATE_BLOCKED:
                bucket = "blocked"
            elif state == PROCESSING_STATE_FAILED:
                bucket = "failed"
            elif state in (PROCESSING_STATE_PENDING, PROCESSING_STATE_PROCESSING):
                bucket = "stuck"
            else:
                # No record, or recorded as cancelled_before_apply but paid again.
                bucket = "missed"
        elif state == PROCESSING_STATE_APPLIED:
            bucket = "reversed"
        elif _is_paid(order) and not is_cancelled_order(order):
            bucket = "paid_not_deductible"
        else:
            bucket = "not_a_sale"
        buckets[bucket].append(entry)

    return buckets


def paid_not_deductible_patterns(buckets):
    counts = Counter(entry["source"] for entry in buckets["paid_not_deductible"])
    return {
        source: count
        for source, count in sorted(counts.items())
        if count >= PAID_NOT_DEDUCTIBLE_PATTERN_THRESHOLD
    }


def problem_count(report):
    return sum(len(report["buckets"][name]) for name in PROBLEM_BUCKETS)


def needs_alert(report):
    return problem_count(report) > 0 or bool(report["patterns"])


def explain(entries, client, binding):
    """Dry-run each order through the worker's projection and record why it would not apply."""
    for entry in entries:
        try:
            result = process_orders(
                [entry["order_id"]], apply_changes=False, client=client, binding=binding
            )
        except Exception as error:
            entry["reason"] = f"could not dry-run: {error}"
            entry["would_apply_now"] = False
            continue
        reasons = [skipped["reason"] for skipped in result.get("skipped_line_items") or []]
        reasons += [skipped["reason"] for skipped in result.get("skipped_orders") or []]
        entry["reason"] = "; ".join(dict.fromkeys(reasons)) or None
        entry["would_apply_now"] = not reasons and bool(result.get("projected_orders"))


def fetch_orders_for_day(client, location_id, day):
    """Every order at the location created on this shop day."""
    start, end = day_window(day)
    orders = []
    cursor = None
    while True:
        response = client.orders.search(
            location_ids=[location_id],
            cursor=cursor,
            limit=500,
            query={"filter": {"date_time_filter": {"created_at": {"start_at": start, "end_at": end}}}},
        )
        orders.extend(response.orders or [])
        cursor = response.cursor
        if not cursor:
            break
    # Square's range end may be inclusive; keep exactly this local day.
    iso_day = day.isoformat()
    return [order for order in orders if local_day_of(order.created_at) == iso_day]


def build_report(day, orders, records_by_order_id):
    buckets = classify(orders, records_by_order_id)
    return {
        "day": day.isoformat(),
        "buckets": buckets,
        "patterns": paid_not_deductible_patterns(buckets),
        "totals": {
            "orders": len(orders),
            "applied_orders": len(buckets["applied"]),
            "applied_items": sum(entry["item_count"] for entry in buckets["applied"]),
            "problems": sum(len(buckets[name]) for name in PROBLEM_BUCKETS),
            "not_a_sale": len(buckets["not_a_sale"]),
            "paid_not_deductible": len(buckets["paid_not_deductible"]),
        },
    }


def _reconcile_day(client, location_id, day):
    orders = fetch_orders_for_day(client, location_id, day)
    records = {order.id: get_order_processing_record(order.id) for order in orders}
    return build_report(day, orders, records)


def run_daily_reconciliation(merchant_context, day):
    """Reconcile one shop day for one merchant, with reasons for every problem order."""
    client = create_square_client_for_merchant(
        merchant_context.environment, merchant_context.merchant_id
    )
    report = _reconcile_day(client, merchant_context.location_id, day)
    problem_entries = [
        entry
        for name in ("blocked", "failed", "stuck", "missed")
        for entry in report["buckets"][name]
    ]
    if problem_entries:
        binding = get_active_catalog_binding(
            merchant_context.environment,
            merchant_context.merchant_id,
            merchant_context.location_id,
        )
        explain(problem_entries, client, binding)
    return report


def run_weekly_summary(merchant_context, last_day):
    """Totals for the seven shop days ending ``last_day`` (no per-order reasons)."""
    client = create_square_client_for_merchant(
        merchant_context.environment, merchant_context.merchant_id
    )
    days = [last_day - timedelta(days=offset) for offset in range(6, -1, -1)]
    return [_reconcile_day(client, merchant_context.location_id, day) for day in days]


def _local_time(timestamp):
    return to_local(timestamp).strftime("%I:%M %p").lstrip("0").lower()


def format_day_lines(report):
    """Problem detail for the daily email; empty when the day is clean."""
    lines = []
    for name in PROBLEM_BUCKETS:
        entries = report["buckets"][name]
        if not entries:
            continue
        lines.extend(["", f"{BUCKET_TITLES[name]} ({len(entries)})"])
        for entry in sorted(entries, key=lambda item: item["created_at"]):
            lines.append(f"  {_local_time(entry['created_at']):>8}  {entry['source']:<14} {entry['items']}")
            lines.append(f"            order {entry['order_id']} (Square: {entry['state']})")
            if entry.get("reason"):
                lines.append(f"            reason: {entry['reason']}")
            if "would_apply_now" in entry:
                lines.append(f"            would apply now: {'yes' if entry['would_apply_now'] else 'no'}")
    if report["patterns"]:
        lines.extend(["", "PAID BUT NOT DEDUCTIBLE, by channel"])
        for source, count in report["patterns"].items():
            lines.append(
                f"  {source}: {count}  (pattern threshold is {PAID_NOT_DEDUCTIBLE_PATTERN_THRESHOLD})"
            )
    return lines


def format_totals_line(report):
    totals = report["totals"]
    return (
        f"Day totals: {totals['orders']} orders in Square, {totals['applied_orders']} deducted "
        f"({totals['applied_items']} items), {totals['problems']} not deducted, "
        f"{totals['not_a_sale']} not sales (drafts, unpaid, cancelled)."
    )


def format_weekly_lines(day_reports):
    lines = []
    for report in day_reports:
        totals = report["totals"]
        status = "clean" if not needs_alert(report) else f"{totals['problems']} not deducted"
        lines.append(
            f"  {report['day']}  {totals['orders']:>4} orders  {totals['applied_orders']:>4} deducted  "
            f"{totals['applied_items']:>4} items  {status}"
        )
    week_orders = sum(report["totals"]["orders"] for report in day_reports)
    week_applied = sum(report["totals"]["applied_orders"] for report in day_reports)
    week_items = sum(report["totals"]["applied_items"] for report in day_reports)
    week_problems = sum(report["totals"]["problems"] for report in day_reports)
    lines.append(
        f"  week       {week_orders:>4} orders  {week_applied:>4} deducted  {week_items:>4} items  "
        f"{week_problems} not deducted"
    )
    return lines


def weekly_problem_count(day_reports):
    return sum(problem_count(report) for report in day_reports)
