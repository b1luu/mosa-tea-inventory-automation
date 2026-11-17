"""One-off helper for creating a canary itemized order against a merchant's
catalog, then auto-paying it via Square's sandbox test card. Fires the same
``payment.updated`` / ``order.fulfillment.updated`` webhooks a real POS would
fire — exercising our webhook ingress + worker pipeline end-to-end.

USAGE (sandbox only — uses sandbox test card nonce):

    python -m scripts.create_test_order \\
        --environment sandbox \\
        --merchant-id <merchant_id> \\
        --location-id <location_id> \\
        --variation-id <catalog_variation_id> \\
        [--quantity 1]

The variation_id should be a *sold* item in the merchant's catalog (e.g., the
Matcha Latte variation, not a backend inventory item). Find it via
``python -m scripts.inspect_catalog_object --merchant ... <id>`` or pull it
from the binding's ``sold_variation_aliases`` keys.

Reads the merchant's OAuth token from DynamoDB + Secrets Manager via the
existing ``create_square_client_for_merchant`` path.
"""

import argparse
import uuid

from app.client import create_square_client_for_merchant


SANDBOX_TEST_CARD_NONCE = "cnon:card-nonce-ok"


def main():
    parser = argparse.ArgumentParser(
        prog="create_test_order",
        description="Create + auto-pay an itemized canary order to fire the deduction pipeline.",
    )
    parser.add_argument("--environment", required=True, choices=["sandbox"],
                        help="Sandbox only — uses Square's sandbox test card nonce.")
    parser.add_argument("--merchant-id", required=True)
    parser.add_argument("--location-id", required=True)
    parser.add_argument("--variation-id", required=True,
                        help="Catalog variation ID of the sold item (NOT backend inventory).")
    parser.add_argument("--quantity", default="1", help="Quantity to order (default 1)")
    args = parser.parse_args()

    client = create_square_client_for_merchant(args.environment, args.merchant_id)

    # 1. Create the order
    print(f"Creating order: 1x variation {args.variation_id} at location {args.location_id}")
    order_resp = client.orders.create(
        idempotency_key=str(uuid.uuid4()),
        order={
            "location_id": args.location_id,
            "line_items": [
                {
                    "catalog_object_id": args.variation_id,
                    "quantity": args.quantity,
                }
            ],
        },
    )
    order = order_resp.order
    print(f"  ✓ Order created: id={order.id}")
    print(f"    total: {order.total_money.amount} {order.total_money.currency}")

    # 2. Pay the order with sandbox test card (no real money moves)
    print("Paying order with sandbox test card nonce...")
    payment_resp = client.payments.create(
        idempotency_key=str(uuid.uuid4()),
        source_id=SANDBOX_TEST_CARD_NONCE,
        amount_money={
            "amount": int(order.total_money.amount),
            "currency": order.total_money.currency,
        },
        order_id=order.id,
        location_id=args.location_id,
    )
    payment = payment_resp.payment
    print(f"  ✓ Payment created: id={payment.id}, status={payment.status}")
    print("  ✓ Order should now be complete; Square will fire payment.updated webhook")
    print("")
    print("Watch for the webhook in the worker logs:")
    print("  aws logs tail /aws/lambda/mosa-tea-webhook-worker --region us-west-2 --follow")
    print("")
    print(f"order_id={order.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
