import json
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from app.admin_routes import admin_router
from app.catalog_change_search import (
    get_latest_updated_at,
    search_changed_catalog_objects,
    summarize_changed_object,
)
from app.catalog_sync_state import get_or_create_last_synced_at, update_last_synced_at
from app.config import (
    get_square_webhook_signature_key,
    get_square_webhook_notification_url,
)
from app.job_dispatcher import dispatch_webhook_job
from app.order_processing_store import get_order_processing_state
from app.webhook_event_store import (
    EVENT_STATUS_ENQUEUED,
    EVENT_STATUS_FAILED,
    EVENT_STATUS_IGNORED,
    EVENT_STATUS_RECEIVED,
    has_webhook_event,
    record_webhook_event,
    set_webhook_event_status,
)
from square.utils.webhooks_helper import verify_signature

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(admin_router)


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


def _record_square_webhook_event(payload, order_event_data, status):
    data = payload.get("data", {})
    record_webhook_event(
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


def _dispatch_order_webhook_job(job, event_id, background_tasks):
    try:
        dispatch_webhook_job(job, background_tasks=background_tasks)
    except Exception as exc:
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_FAILED)
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
        set_webhook_event_status(event_id, EVENT_STATUS_ENQUEUED)


@app.post("/webhook/square")
async def square_webhook(request: Request, background_tasks: BackgroundTasks):
    signature_header = request.headers.get("x-square-hmacsha256-signature", "")
    request_body = (await request.body()).decode("utf-8")

    is_valid = verify_signature(
        request_body=request_body,
        signature_header=signature_header,
        signature_key=get_square_webhook_signature_key(),
        notification_url=get_square_webhook_notification_url(),
    )

    if not is_valid:
        return Response(
            content='{"error":"invalid signature"}',
            media_type="application/json",
            status_code=403,
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
    duplicate_event = bool(event_id and has_webhook_event(event_id))

    if event_type in {"order.created", "order.updated"}:
        if duplicate_event:
            print("order_webhook_duplicate:")
            print(json.dumps({"event_id": event_id, "event_type": event_type}, indent=2))
            return {"ok": True}

        current_processing_state = (
            get_order_processing_state(order_id) if order_id else None
        )
        should_start_processing = (
            order_state == "COMPLETED"
            and order_id is not None
            and current_processing_state is None
        )

        if event_id:
            _record_square_webhook_event(
                payload,
                order_event_data,
                EVENT_STATUS_RECEIVED if should_start_processing else EVENT_STATUS_IGNORED,
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
            )

        processing_state_after = (
            get_order_processing_state(order_id) if order_id else None
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
        return {"ok": True}

    if payload.get("type") == "catalog.version.updated":
        if duplicate_event:
            print("catalog_webhook_duplicate:")
            print(json.dumps({"event_id": event_id, "event_type": event_type}, indent=2))
            return {"ok": True}

        if event_id:
            _record_square_webhook_event(payload, order_event_data, EVENT_STATUS_ENQUEUED)

        last_synced_at = get_or_create_last_synced_at()
        print("catalog_webhook:")
        print(
            json.dumps(
                {
                    "event_type": event_type,
                    "event_id": event_id,
                    "last_synced_at": last_synced_at,
                },
                indent=2,
            )
        )

        changed_objects = search_changed_catalog_objects(last_synced_at)
        changed_summaries = [
            summarize_changed_object(catalog_object)
            for catalog_object in changed_objects
        ]
        print("catalog_changes:")
        print(json.dumps(changed_summaries, indent=2))

        latest_object_updated_at = get_latest_updated_at(changed_objects)

        if not latest_object_updated_at:
            print("checkpoint unchanged: no changed objects found")
            return {"ok": True}

        if _parse_rfc3339(latest_object_updated_at) <= _parse_rfc3339(last_synced_at):
            print("checkpoint unchanged: latest changed object is not newer")
            return {"ok": True}

        update_last_synced_at(latest_object_updated_at)
        print(f"updated checkpoint to: {latest_object_updated_at}")
        if event_id:
            set_webhook_event_status(event_id, EVENT_STATUS_PROCESSED)

    return {"ok": True}
