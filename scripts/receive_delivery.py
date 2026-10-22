"""Record a supplier delivery in Square as received stock (NONE -> IN_STOCK).

Quantities are in stock units, the same units as the count sheet (bags,
bottles, boxes, cans). Dry run by default; pass --apply to write.

Safe to re-run: the delivery id fixes the idempotency key, so the same
delivery can't be added twice. Log-only items (no Square item, e.g. oat milk)
and items missing from the active binding are refused.

    ./.venv/bin/python -m scripts.receive_delivery \\
        --merchant MLXZ38BC27GAD --environment production --location-id LZ4JV6WQHPQVE \\
        --delivery-id delivery-2026-10-21 \\
        black_tea=10 green_tea=40 tgy=70 [--apply]

Also add the delivery to the count sheet's "in" column: recipe calibration
reads deliveries from there.
"""

import argparse
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.client import create_square_client_for_merchant
from app.merchant_store import get_active_catalog_binding
from app.order_inventory_projection import load_inventory_item_map


def parse_quantities(pairs):
    """Parse ``key=qty`` pairs into {inventory_key: Decimal}; quantities must be positive."""
    received = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"Expected inventory_key=quantity, got {pair!r}.")
        try:
            quantity = Decimal(raw)
        except InvalidOperation as error:
            raise ValueError(f"Quantity for {key!r} is not a number: {raw!r}.") from error
        if quantity <= 0:
            raise ValueError(f"Quantity for {key!r} must be positive, got {raw}.")
        if key in received:
            raise ValueError(f"{key!r} is listed twice.")
        received[key] = quantity
    return received


def find_unreceivable(received, inventory_items, inventory_variation_ids):
    """Keys that can't be received in Square: unknown, log-only, or not in the binding."""
    problems = {}
    for key in received:
        item = inventory_items.get(key)
        if item is None:
            problems[key] = "not in data/inventory_item_map.json"
        elif item.get("tracking") == "log_only":
            problems[key] = "log-only item (no Square item)"
        elif key not in inventory_variation_ids:
            problems[key] = "not in the active binding"
    return problems


def build_changes(received, inventory_variation_ids, location_id, delivery_id, occurred_at):
    return [
        {
            "type": "ADJUSTMENT",
            "adjustment": {
                "reference_id": f"{delivery_id}:{key}",
                "catalog_object_id": inventory_variation_ids[key],
                "from_state": "NONE",
                "to_state": "IN_STOCK",
                "location_id": location_id,
                "quantity": str(quantity),
                "occurred_at": occurred_at,
            },
        }
        for key, quantity in received.items()
    ]


def idempotency_key(delivery_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mosa-tea:{delivery_id}"))


def _counts(client, ids, location_id):
    by_id = {
        count.catalog_object_id: Decimal(count.quantity)
        for count in client.inventory.batch_get_counts(
            catalog_object_ids=list(ids.values()), location_ids=[location_id], states=["IN_STOCK"]
        )
    }
    return {key: by_id.get(object_id, Decimal(0)) for key, object_id in ids.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--merchant", required=True)
    parser.add_argument("--environment", required=True, choices=["sandbox", "production"])
    parser.add_argument("--location-id", required=True)
    parser.add_argument("--delivery-id", required=True, help="Unique per delivery, e.g. delivery-2026-10-21")
    parser.add_argument("--apply", action="store_true", help="Write to Square (default: dry run)")
    parser.add_argument("items", nargs="+", help="inventory_key=quantity in stock units")
    args = parser.parse_args()

    try:
        received = parse_quantities(args.items)
    except ValueError as error:
        parser.error(str(error))

    inventory_items = load_inventory_item_map()
    binding = get_active_catalog_binding(args.environment, args.merchant, args.location_id)
    all_ids = binding["mapping"]["inventory_variation_ids"]
    problems = find_unreceivable(received, inventory_items, all_ids)
    if problems:
        for key, reason in problems.items():
            print(f"cannot receive {key}: {reason}", file=sys.stderr)
        return 1

    ids = {key: all_ids[key] for key in received}
    client = create_square_client_for_merchant(args.environment, args.merchant)
    before = _counts(client, ids, args.location_id)

    print(f"{'item':16} {'unit':24} {'Square now':>11} {'received':>9} {'after':>11}")
    for key, quantity in received.items():
        item = inventory_items[key]
        unit = f"{item.get('stock_unit') or item['unit']} ({item.get('stock_unit_size', 1):g} {item.get('stock_unit_size_unit') or item['unit']})"
        print(f"{key:16} {unit:24} {before[key]:11.3f} {quantity:9} {before[key] + quantity:11.3f}")

    if not args.apply:
        print("\nDRY RUN: nothing written. Re-run with --apply.")
        return 0

    occurred_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    client.inventory.batch_create_changes(
        idempotency_key=idempotency_key(args.delivery_id),
        changes=build_changes(received, ids, args.location_id, args.delivery_id, occurred_at),
        ignore_unchanged_counts=False,
    )
    after = _counts(client, ids, args.location_id)
    print(f"\nAPPLIED {args.delivery_id}")
    print(f"{'item':16} {'before':>9} {'after':>9} {'diff':>8}")
    for key, quantity in received.items():
        diff = after[key] - before[key]
        flag = "" if diff == quantity else "  CHECK: differs from received (repeat run, or a sale landed meanwhile)"
        print(f"{key:16} {before[key]:9.3f} {after[key]:9.3f} {diff:8.3f}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
