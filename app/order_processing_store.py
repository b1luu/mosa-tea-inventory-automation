from app.order_processing_db import (
    PROCESSING_STATE_APPLIED,
    PROCESSING_STATE_BLOCKED,
    PROCESSING_STATE_FAILED,
    PROCESSING_STATE_PENDING,
    get_order_processing_state as _get_order_processing_state,
    is_order_applied as _is_order_applied,
    list_order_processing_rows as _list_order_processing_rows,
    mark_order_applied as _mark_order_applied,
    mark_order_failed as _mark_order_failed,
    mark_order_pending as _mark_order_pending,
    clear_order_processing_reservation as _clear_order_processing_reservation,
    reserve_order_processing as _reserve_order_processing,
    set_order_processing_state as _set_order_processing_state,
)


def is_order_applied(order_id):
    return _is_order_applied(order_id)


def get_order_processing_state(order_id):
    return _get_order_processing_state(order_id)


def list_order_processing_rows(processing_state=None):
    return _list_order_processing_rows(processing_state=processing_state)


def set_order_processing_state(order_id, processing_state):
    return _set_order_processing_state(order_id, processing_state)


def reserve_order_processing(order_id):
    return _reserve_order_processing(order_id)


def clear_order_processing_reservation(order_id):
    return _clear_order_processing_reservation(order_id)


def mark_order_applied(order_id):
    return _mark_order_applied(order_id)


def mark_order_pending(order_id):
    return _mark_order_pending(order_id)


def mark_order_failed(order_id):
    return _mark_order_failed(order_id)
