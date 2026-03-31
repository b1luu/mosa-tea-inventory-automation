from app.webhook_event_db import (
    EVENT_STATUS_ENQUEUED,
    EVENT_STATUS_FAILED,
    EVENT_STATUS_IGNORED,
    EVENT_STATUS_PROCESSED,
    EVENT_STATUS_RECEIVED,
    get_webhook_event as _get_webhook_event,
    has_webhook_event as _has_webhook_event,
    list_webhook_events as _list_webhook_events,
    set_webhook_event_status as _set_webhook_event_status,
    upsert_webhook_event as _upsert_webhook_event,
)


def get_webhook_event(event_id):
    return _get_webhook_event(event_id)


def has_webhook_event(event_id):
    return _has_webhook_event(event_id)


def record_webhook_event(**kwargs):
    return _upsert_webhook_event(**kwargs)


def set_webhook_event_status(event_id, status):
    return _set_webhook_event_status(event_id, status)


def list_webhook_events(status=None):
    return _list_webhook_events(status=status)
