import json

from fastapi import FastAPI, Request, Response
from app.catalog_change_search import (
    retrieve_variation_details,
    search_changed_catalog_objects,
    summarize_changed_object,
    summarize_variation_details,
)
from app.component_variation_map import build_variation_to_component_map
from app.catalog_sync_state import get_or_create_last_synced_at, update_last_synced_at
from app.config import (
    get_square_webhook_signature_key,
    get_square_webhook_notification_url,
)
from square.utils.webhooks_helper import verify_signature

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
        variation_to_component = build_variation_to_component_map()
        last_synced_at = get_or_create_last_synced_at()
        print(f"last_synced_at: {last_synced_at}")

        changed_objects = search_changed_catalog_objects(last_synced_at)
        changed_summaries = [
            summarize_changed_object(catalog_object)
            for catalog_object in changed_objects
        ]
        print("changed_objects:")
        print(json.dumps(changed_summaries, indent=2))

        tracked_variation_changes = [
            catalog_object
            for catalog_object in changed_objects
            if catalog_object.type == "ITEM_VARIATION"
            and catalog_object.id in variation_to_component
        ]

        if tracked_variation_changes:
            print("tracked variation changes:")
            print(
                json.dumps(
                    [
                        summarize_changed_object(catalog_object)
                        for catalog_object in tracked_variation_changes
                    ],
                    indent=2,
                )
            )
            changed_components = [
                variation_to_component[catalog_object.id]
                for catalog_object in tracked_variation_changes
            ]
            print("changed components:")
            print(json.dumps(changed_components, indent=2))

            tracked_variation_details = [
                summarize_variation_details(
                    retrieve_variation_details(catalog_object.id)
                )
                for catalog_object in tracked_variation_changes
            ]
            print("tracked variation details:")
            print(json.dumps(tracked_variation_details, indent=2))

        catalog_version = payload.get("data", {}).get("object", {}).get(
            "catalog_version", {}
        )
        updated_at = catalog_version.get("updated_at")

        if updated_at:
            update_last_synced_at(updated_at)
            print(f"updated checkpoint to: {updated_at}")

    return {"ok": True}
