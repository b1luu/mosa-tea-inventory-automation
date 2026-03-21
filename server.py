import json

from fastapi import FastAPI, Request, Response
from app.catalog_change_search import (
    search_changed_catalog_objects,
    summarize_changed_object,
)
from app.catalog_sync_state import get_or_create_last_synced_at, update_last_synced_at
from app.config import (
    get_square_webhook_signature_key,
    get_square_webhook_notification_url,
)
from square.utils.webhooks_helper import verify_signature

# Minimal viable Square webhook receiver for learning.

app = FastAPI()


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

        catalog_version = payload.get("data", {}).get("object", {}).get(
            "catalog_version", {}
        )
        updated_at = catalog_version.get("updated_at")

        if updated_at:
            update_last_synced_at(updated_at)
            print(f"updated checkpoint to: {updated_at}")

    return {"ok": True}
