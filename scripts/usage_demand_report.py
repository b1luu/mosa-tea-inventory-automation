"""Daily demand per ingredient from the usage log, in recipe units and stock units.

Defaults to the ingredients that are never recounted from the sheet: every item
marked ``"tracking": "log_only"`` or ``"tracking": "demand"`` in
``data/inventory_item_map.json`` (oat milk, milk, frozen mango, frozen strawberry).

    USAGE_LOG_STORE_MODE=dynamodb DYNAMODB_USAGE_LOG_TABLE=mosa-tea-usage-log-prod AWS_REGION=us-west-2 \\
    ./.venv/bin/python -m scripts.usage_demand_report \\
        --merchant MLXZ38BC27GAD \\
        --environment production \\
        --location-id LZ4JV6WQHPQVE \\
        [--days 14] [--keys oat_milk,milk] [--timezone America/Los_Angeles]

Days run midnight to midnight in the shop's time zone (California by default,
which switches between PST and PDT automatically). The usage log stores UTC
sale times, so the window is converted to UTC for the query and each sale is
converted back to local time before it is assigned to a day.
"""

import argparse
from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.order_inventory_projection import load_inventory_item_map
from app.shop_time import SHOP_TIMEZONE, local_day_of, local_day_window
from app.usage_log_store import list_usage


def _default_keys(inventory_items):
    return sorted(
        key
        for key, item in inventory_items.items()
        if item.get("tracking") in {"log_only", "demand"}
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--merchant", required=True)
    parser.add_argument("--environment", required=True, choices=["sandbox", "production"])
    parser.add_argument("--location-id", required=True)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--keys", help="Comma-separated inventory keys; defaults to demand-tracked items")
    parser.add_argument("--timezone", default=SHOP_TIMEZONE, help="IANA time zone for day boundaries")
    args = parser.parse_args()
    tz = ZoneInfo(args.timezone)

    inventory_items = load_inventory_item_map()
    keys = args.keys.split(",") if args.keys else _default_keys(inventory_items)
    start, end, days = local_day_window(args.days, tz)

    for key in keys:
        item = inventory_items[key]
        rows = list_usage(
            args.environment, args.merchant, args.location_id, key, start, end
        )
        per_day = defaultdict(Decimal)
        for row in rows:
            per_day[local_day_of(row["sold_at"], tz)] += Decimal(str(row["amount"]))

        total = sum(per_day.values(), Decimal("0"))
        stock_size = Decimal(str(item.get("stock_unit_size") or 0))
        stock_unit = item.get("stock_unit") or item["unit"]

        def in_stock_units(amount):
            return f" ({amount / stock_size:.2f} {stock_unit})" if stock_size else ""

        print(f"\n{key} [{item.get('tracking', 'counted')}] - {len(rows)} orders, last {args.days} days ({args.timezone})")
        for day in days:
            amount = per_day.get(day, Decimal("0"))
            print(f"  {day}  {amount:>10.1f} {item['unit']}{in_stock_units(amount)}")
        daily_average = total / args.days
        print(f"  total {total:.1f} {item['unit']}{in_stock_units(total)}; "
              f"average {daily_average:.1f} {item['unit']}/day{in_stock_units(daily_average)}")


if __name__ == "__main__":
    main()
