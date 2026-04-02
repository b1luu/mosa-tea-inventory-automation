import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from square.utils.webhooks_helper import verify_signature

from app.catalog_change_search import (
    get_latest_updated_at,
    search_changed_catalog_objects,
    summarize_changed_object,
)
from app.catalog_sync_state import get_or_create_last_synced_at, update_last_synced_at
from app.config import (
    get_square_webhook_notification_url,
    get_square_webhook_signature_key,
)
from app.job_dispatcher import dispatch_webhook_job
from app.order_processing_store import (
    clear_order_processing_reservation,
    get_order_processing_state,
    reserve_order_processing,
)
from app.webhook_event_store import (
    EVENT_STATUS_ENQUEUED,
    EVENT_STATUS_FAILED,
    EVENT_STATUS_IGNORED,
    EVENT_STATUS_PROCESSED,
    EVENT_STATUS_RECEIVED,
    get_webhook_event,
    record_webhook_event,
    set_webhook_event_status,
)


@dataclass(frozen=True)
class WebhookIngressResponse:
    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class WebhookIngressDependencies:
    verify_signature: Callable[..., bool]
    get_square_webhook_signature_key: Callable[[], str]
    get_square_webhook_notification_url: Callable[[], str]
    get_webhook_event: Callable[[str | None], dict[str, Any] | None]
    get_order_processing_state: Callable[[str], str | None]
    reserve_order_processing: Callable[[str], bool]
    clear_order_processing_reservation: Callable[[str], Any]
    record_webhook_event: Callable[..., Any]
    dispatch_webhook_job: Callable[..., Any]
    set_webhook_event_status: Callable[[str, str], Any]
    get_or_create_last_synced_at: Callable[[], str]
    search_changed_catalog_objects: Callable[[str], list[Any]]
    get_latest_updated_at: Callable[[list[Any]], str | None]
    summarize_changed_object: Callable[[Any], Any]
    update_last_synced_at: Callable[[str], Any]


def default_webhook_ingress_dependencies():
    return WebhookIngressDependencies(
        verify_signature=verify_signature,
        get_square_webhook_signature_key=get_square_webhook_signature_key,
        get_square_webhook_notification_url=get_square_webhook_notification_url,
        get_webhook_event=get_webhook_event,
        get_order_processing_state=get_order_processing_state,
        reserve_order_processing=reserve_order_processing,
        clear_order_processing_reservation=clear_order_processing_reservation,
        record_webhook_event=record_webhook_event,
        dispatch_webhook_job=dispatch_webhook_job,
        set_webhook_event_status=set_webhook_event_status,
        get_or_create_last_synced_at=get_or_create_last_synced_at,
        search_changed_catalog_objects=search_changed_catalog_objects,
        get_latest_updated_at=get_latest_updated_at,
        summarize_changed_object=summarize_changed_object,
        update_last_synced_at=update_last_synced_at,
    )


def _parse_rfc3339(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def _get_event_type(payload):
    return payload.get("type", "")


def _get_order_event_data(payload):
    data = payload.get("data", {})
    object_data = data.get("object", {})
    return object_data.get("order_created") or object_data.get("order_updated") or {}


def _get_order_id_from_payload(payload):
    order_data = _get_order_event_data(payload)
    return order_data.get("order_id")


def _record_square_webhook_event(payload, order_event_data, status, deps):
    data = payload.get("data", {})
    deps.record_webhook_event(
        event_id=payload["event_id"],
        merchant_id=payload["merchant_id"],
        event_type=payload["type"],
        event_created_at=payload.get("created_at"),
        data_type=data.get("type"),
        data_id=data.get("id"),
        order_id=order_event_data.get("order_id"),
        order_state=order_event_data.get("state"),
        location_id=order_event_data.get("location_id"),
        version=order_event_data.get("version"),
        status=status,
    )


def _dispatch_order_webhook_job(job, event_id, background_tasks, deps):
    try:
        deps.dispatch_webhook_job(job, background_tasks=background_tasks)
    except Exception as exc:
        order_id = job.get("order_id")
        if order_id:
            deps.clear_order_processing_reservation(order_id)
        if event_id:
            deps.set_webhook_event_status(event_id, EVENT_STATUS_FAILED)
        print("order_webhook_dispatch_failed:")
        print(
            json.dumps(
                {
                    "event_id": event_id,
                    "order_id": job.get("order_id"),
                    "event_type": job.get("event_type"),
                    "error": str(exc),
                },
                indent=2,
            )
        )
        raise

    if event_id:
        deps.set_webhook_event_status(event_id, EVENT_STATUS_ENQUEUED)


def _process_catalog_webhook_event(event_id, deps):
    try:
        last_synced_at = deps.get_or_create_last_synced_at()
        print("catalog_webhook:")
        print(
            json.dumps(
                {
                    "event_type": "catalog.version.updated",
                    "event_id": event_id,
                    "last_synced_at": last_synced_at,
                },
                indent=2,
            )
        )

        changed_objects = deps.search_changed_catalog_objects(last_synced_at)
        changed_summaries = [
            deps.summarize_changed_object(catalog_object)
            for catalog_object in changed_objects
        ]
        print("catalog_changes:")
        print(json.dumps(changed_summaries, indent=2))

        latest_object_updated_at = deps.get_latest_updated_at(changed_objects)

        if not latest_object_updated_at:
            print("checkpoint unchanged: no changed objects found")
        elif _parse_rfc3339(latest_object_updated_at) <= _parse_rfc3339(last_synced_at):
            print("checkpoint unchanged: latest changed object is not newer")
        else:
            deps.update_last_synced_at(latest_object_updated_at)
            print(f"updated checkpoint to: {latest_object_updated_at}")
    except Exception as exc:
        if event_id:
            deps.set_webhook_event_status(event_id, EVENT_STATUS_FAILED)
        print("catalog_webhook_processing_failed:")
        print(
            json.dumps(
                {
                    "event_id": event_id,
                    "event_type": "catalog.version.updated",
                    "error": str(exc),
                },
                indent=2,
            )
        )
        raise

    if event_id:
        deps.set_webhook_event_status(event_id, EVENT_STATUS_PROCESSED)


def handle_square_webhook_request(
    request_body,
    signature_header,
    background_tasks=None,
    deps=None,
):
    deps = deps or default_webhook_ingress_dependencies()

    is_valid = deps.verify_signature(
        request_body=request_body,
        signature_header=signature_header,
        signature_key=deps.get_square_webhook_signature_key(),
        notification_url=deps.get_square_webhook_notification_url(),
    )

    if not is_valid:
        return WebhookIngressResponse(
            status_code=403,
            body={"error": "invalid signature"},
        )

    payload = json.loads(request_body)
    event_type = _get_event_type(payload)
    order_event_data = _get_order_event_data(payload)
    order_id = _get_order_id_from_payload(payload)
    order_state = order_event_data.get("state")
    location_id = order_event_data.get("location_id")
    updated_at = order_event_data.get("updated_at")
    version = order_event_data.get("version")
    event_id = payload.get("event_id")
    existing_event = deps.get_webhook_event(event_id) if event_id else None
    duplicate_event = bool(
        existing_event and existing_event.get("status") != EVENT_STATUS_FAILED
    )

    if event_type in {"order.created", "order.updated"}:
        if duplicate_event:
            print("order_webhook_duplicate:")
            print(json.dumps({"event_id": event_id, "event_type": event_type}, indent=2))
            return WebhookIngressResponse(status_code=200, body={"ok": True})

        current_processing_state = (
            deps.get_order_processing_state(order_id) if order_id else None
        )
        should_start_processing = False
        if (
            order_state == "COMPLETED"
            and order_id is not None
            and current_processing_state is None
        ):
            should_start_processing = deps.reserve_order_processing(order_id)
            if not should_start_processing:
                current_processing_state = deps.get_order_processing_state(order_id)

        if event_id:
            _record_square_webhook_event(
                payload,
                order_event_data,
                EVENT_STATUS_RECEIVED if should_start_processing else EVENT_STATUS_IGNORED,
                deps,
            )

        if should_start_processing:
            _dispatch_order_webhook_job(
                {
                    "event_id": event_id,
                    "merchant_id": payload.get("merchant_id"),
                    "event_type": event_type,
                    "order_id": order_id,
                },
                event_id,
                background_tasks,
                deps,
            )

        processing_state_after = (
            deps.get_order_processing_state(order_id) if order_id else None
        )

        print("order_webhook:")
        print(
            json.dumps(
                {
                    "event_type": event_type,
                    "order_id": order_id,
                    "state": order_state,
                    "location_id": location_id,
                    "updated_at": updated_at,
                    "version": version,
                    "event_id": event_id,
                    "current_processing_state": current_processing_state,
                    "marked_pending": should_start_processing,
                    "processing_state_after": processing_state_after,
                },
                indent=2,
            )
        )
        return WebhookIngressResponse(status_code=200, body={"ok": True})

    if event_type == "catalog.version.updated":
        if duplicate_event:
            print("catalog_webhook_duplicate:")
            print(json.dumps({"event_id": event_id, "event_type": event_type}, indent=2))
            return WebhookIngressResponse(status_code=200, body={"ok": True})

        if event_id:
            _record_square_webhook_event(
                payload,
                order_event_data,
                EVENT_STATUS_RECEIVED,
                deps,
            )

        _process_catalog_webhook_event(event_id, deps)
        return WebhookIngressResponse(status_code=200, body={"ok": True})

    return WebhookIngressResponse(status_code=200, body={"ok": True})
