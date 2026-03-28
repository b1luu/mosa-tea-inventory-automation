import json
from datetime import datetime

from fastapi import FastAPI, Request, Response
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
from square.utils.webhooks_helper import verify_signature

app = FastAPI()


def _parse_rfc3339(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

def _get_event_type(payload):
    return payload.get("type", "")

def _get_order_id_from_payload(payload):
    data = payload.get("data", {})
    object_data = data.get("object", {})
    order_data = object_data.get("order_created") or object_data.get("order_updated") or {}
    return order_data.get("order_id")

@app.post("/webhook/square")
async def square_webhook(request: Request):
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
    headers = dict(request.headers)
    pretty_body = json.dumps(payload, indent=2)

    event_type = _get_event_type(payload)
    order_id = _get_order_id_from_payload(payload)

    if event_type in {"order.created", "order.updated"}:
        print("order_webhook:")
        print(
            json.dumps(
                {
                    "event_type": event_type,
                    "order_id": order_id,
                },
                indent=2,
            )
        )

    print("event_type:")
    print(event_type)
    print("order_id:")
    print(order_id)

    print(headers)
    print(pretty_body)

    if payload.get("type") == "catalog.version.updated":
        last_synced_at = get_or_create_last_synced_at()
        print(f"last_synced_at: {last_synced_at}")

        changed_objects = search_changed_catalog_objects(last_synced_at)
        changed_summaries = [
            summarize_changed_object(catalog_object)
            for catalog_object in changed_objects
        ]
        print("changed_objects:")
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

    return {"ok": True}
