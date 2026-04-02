from app.config import get_webhook_event_store_mode
from app.webhook_event_db import (
    EVENT_STATUS_ENQUEUED,
    EVENT_STATUS_FAILED,
    EVENT_STATUS_IGNORED,
    EVENT_STATUS_PROCESSED,
    EVENT_STATUS_RECEIVED,
)
from app import webhook_event_db, webhook_event_dynamodb


def _get_store_backend():
    store_mode = get_webhook_event_store_mode()
    if store_mode == "sqlite":
        return webhook_event_db
    if store_mode == "dynamodb":
        return webhook_event_dynamodb
    raise ValueError(f"Unsupported webhook event store mode: {store_mode}")


def get_webhook_event(event_id):
    return _get_store_backend().get_webhook_event(event_id)


def has_webhook_event(event_id):
    return _get_store_backend().has_webhook_event(event_id)


def record_webhook_event(**kwargs):
    return _get_store_backend().upsert_webhook_event(**kwargs)


def create_webhook_event(**kwargs):
    backend = _get_store_backend()
    if hasattr(backend, "create_webhook_event"):
        return backend.create_webhook_event(**kwargs)
    return backend.upsert_webhook_event(**kwargs)


def set_webhook_event_status(event_id, status):
    return _get_store_backend().set_webhook_event_status(event_id, status)


def list_webhook_events(status=None):
    return _get_store_backend().list_webhook_events(status=status)
