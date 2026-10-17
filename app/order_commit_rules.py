"""Which Square orders commit inventory.

An order commits when Square marks it ``COMPLETED``, or when it is a paid
Kiosk order. Kiosk orders are paid at the kiosk and then left ``OPEN`` with
their fulfillment at ``PROPOSED``; in the 30 days to 2026-10-17 not one of 884
reached ``COMPLETED``, so waiting for completion meant they were never deducted
(37% of items sold). See docs/order-state-handling-decision.md.

The paid-Kiosk rule is limited to the Kiosk source on purpose: other channels
(POS, Square Online, delivery apps) complete their orders normally, and Square
Online orders can be cancelled after payment.
"""

from app.client import create_square_client
from app.merchant_store import resolve_merchant_access_token

KIOSK_SOURCE_NAME = "Kiosk"


def _source_name(order):
    return getattr(getattr(order, "source", None), "name", None)


def is_paid_kiosk_order(order):
    """OPEN, from the Kiosk, with a tender and nothing left to pay."""
    if getattr(order, "state", None) != "OPEN":
        return False
    if _source_name(order) != KIOSK_SOURCE_NAME:
        return False
    if not getattr(order, "tenders", None):
        return False
    net_amount_due = getattr(order, "net_amount_due_money", None)
    return net_amount_due is None or (getattr(net_amount_due, "amount", 0) or 0) == 0


def is_committable_order(order):
    return getattr(order, "state", None) == "COMPLETED" or is_paid_kiosk_order(order)


def fetch_is_paid_kiosk_order(environment, merchant_id, order_id):
    """Fetch one order and apply :func:`is_paid_kiosk_order`.

    Used by webhook ingress, whose ``order.updated`` payload carries the state
    but not the source or tenders. Reads the stored token without refreshing:
    ingress has no OAuth client credentials, and the worker and the scheduled
    refresh keep the token current. Errors propagate so the webhook returns an
    error and Square redelivers it.
    """
    access_token = resolve_merchant_access_token(
        environment, merchant_id, refresh_if_needed=False
    )
    if not access_token:
        raise ValueError(
            f"No Square access token for merchant {merchant_id!r} in {environment!r}."
        )
    client = create_square_client(access_token=access_token, environment_name=environment)
    order = client.orders.get(order_id=order_id).order
    return bool(order) and is_paid_kiosk_order(order)
