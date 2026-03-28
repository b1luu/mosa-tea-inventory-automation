import json
import sys

from app.inventory_stock_units import convert_inventory_amount_to_stock_unit


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: ./.venv/bin/python -m scripts.show_stock_unit_conversion "
            "<inventory_key> <amount>"
        )
        return 1

    inventory_key = sys.argv[1]
    amount = sys.argv[2]
    print(json.dumps(convert_inventory_amount_to_stock_unit(inventory_key, amount), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
