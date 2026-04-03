from app.config import get_order_processing_store_mode
from app import order_processing_dynamodb
from app.order_processing_db import (
    PROCESSING_STATE_APPLIED,
    PROCESSING_STATE_BLOCKED,
    PROCESSING_STATE_FAILED,
    PROCESSING_STATE_PENDING,
    PROCESSING_STATE_PROCESSING,
)
from app import order_processing_db


def _get_store_backend():
    store_mode = get_order_processing_store_mode()
    if store_mode == "sqlite":
        return order_processing_db
    if store_mode == "dynamodb":
        return order_processing_dynamodb
    raise ValueError(f"Unsupported order processing store mode: {store_mode}")


def is_order_applied(order_id):
    return _get_store_backend().is_order_applied(order_id)


def get_order_processing_state(order_id):
    return _get_store_backend().get_order_processing_state(order_id)


def list_order_processing_rows(processing_state=None):
    return _get_store_backend().list_order_processing_rows(
        processing_state=processing_state
    )


def set_order_processing_state(order_id, processing_state):
    return _get_store_backend().set_order_processing_state(order_id, processing_state)


def transition_order_processing_state(order_id, from_state, to_state):
    backend = _get_store_backend()
    if hasattr(backend, "transition_order_processing_state"):
        return backend.transition_order_processing_state(order_id, from_state, to_state)
    current_state = backend.get_order_processing_state(order_id)
    if current_state != from_state:
        return False
    backend.set_order_processing_state(order_id, to_state)
    return True


def reserve_order_processing(order_id):
    return _get_store_backend().reserve_order_processing(order_id)


def claim_order_processing(order_id):
    backend = _get_store_backend()
    if hasattr(backend, "claim_order_processing"):
        return backend.claim_order_processing(order_id)
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PENDING,
        PROCESSING_STATE_PROCESSING,
    )


def release_order_processing_claim(order_id):
    backend = _get_store_backend()
    if hasattr(backend, "release_order_processing_claim"):
        return backend.release_order_processing_claim(order_id)
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PROCESSING,
        PROCESSING_STATE_PENDING,
    )


def requeue_order_processing(order_id):
    backend = _get_store_backend()
    if hasattr(backend, "requeue_order_processing"):
        return backend.requeue_order_processing(order_id)
    if transition_order_processing_state(
        order_id,
        PROCESSING_STATE_FAILED,
        PROCESSING_STATE_PENDING,
    ):
        return True
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_BLOCKED,
        PROCESSING_STATE_PENDING,
    )


def clear_order_processing_reservation(order_id):
    return _get_store_backend().clear_order_processing_reservation(order_id)


def mark_order_applied(order_id):
    return _get_store_backend().mark_order_applied(order_id)


def mark_order_pending(order_id):
    return _get_store_backend().mark_order_pending(order_id)


def mark_order_failed(order_id):
    return _get_store_backend().mark_order_failed(order_id)


def mark_order_blocked(order_id):
    backend = _get_store_backend()
    if hasattr(backend, "mark_order_blocked"):
        return backend.mark_order_blocked(order_id)
    return transition_order_processing_state(
        order_id,
        PROCESSING_STATE_PROCESSING,
        PROCESSING_STATE_BLOCKED,
    )
