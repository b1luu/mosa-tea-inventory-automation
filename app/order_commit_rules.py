"""Which Square orders commit inventory.

An order commits when it is **paid in full**: ``COMPLETED``, or ``OPEN`` with a
tender and nothing owed, from any channel. Waiting for ``COMPLETED`` depended on
staff marking orders complete, which they often do a day or more late (40% of
Square Online orders) or never (Kiosk), so inventory lagged and orders completed
after a recount were counted twice. See docs/order-state-handling-decision.md
and docs/daily-order-reconciliation-design.md.

Paid-but-``OPEN`` orders are held for ``PAID_ORDER_HOLD_SECONDS`` before they
are applied, so a cancellation shortly after payment lands first. The worker
re-fetches the order when the hold ends.
"""

from app.client import create_square_client
from app.merchant_store import resolve_merchant_access_token

# SQS DelaySeconds caps at 900. Half of post-payment cancellations happen
# within a minute; this covers the typical case.
PAID_ORDER_HOLD_SECONDS = 900


def is_paid_in_full(order):
    """OPEN, with a tender and nothing left to pay. Any channel."""
    if getattr(order, "state", None) != "OPEN":
        return False
    if not getattr(order, "tenders", None):
        return False
    net_amount_due = getattr(order, "net_amount_due_money", None)
    return net_amount_due is None or (getattr(net_amount_due, "amount", 0) or 0) == 0


def is_committable_order(order):
    return getattr(order, "state", None) == "COMPLETED" or is_paid_in_full(order)


def is_cancelled_order(order):
    return getattr(order, "state", None) == "CANCELED"


def fetch_is_paid_in_full(environment, merchant_id, order_id):
    """Fetch one order and apply :func:`is_paid_in_full`.

    Used by webhook ingress, whose ``order.updated`` payload carries the state
    but not the tenders. Reads the stored token without refreshing: ingress has
    no OAuth client credentials, and the worker and the scheduled refresh keep
    the token current. Errors propagate so the webhook returns an error and
    Square redelivers it.
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
    return bool(order) and is_paid_in_full(order)
