from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from square.utils.webhooks_helper import verify_signature

from app.admin_routes import admin_router
from app.catalog_change_search import (
    get_latest_updated_at,
    search_changed_catalog_objects,
    summarize_changed_object,
)
from app.catalog_sync_state import get_or_create_last_synced_at, update_last_synced_at
from app.config import (
    get_square_environment_name,
    get_square_webhook_notification_url,
    get_square_webhook_signature_key,
)
from app.job_dispatcher import dispatch_webhook_job
from app.merchant_store import get_merchant_context
from app.oauth_routes import oauth_router
from app.order_processing_store import (
    clear_order_processing_reservation,
    get_order_processing_state,
    reserve_order_processing,
)
from app.webhook_event_store import (
    EVENT_STATUS_ENQUEUED,
    create_webhook_event,
    EVENT_STATUS_FAILED,
    EVENT_STATUS_IGNORED,
    EVENT_STATUS_PROCESSED,
    EVENT_STATUS_RECEIVED,
    get_webhook_event,
    record_webhook_event,
    set_webhook_event_status,
)
from app.webhook_ingress import (
    WebhookIngressDependencies,
    handle_square_webhook_request,
)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(admin_router)
app.include_router(oauth_router)


def _build_webhook_ingress_dependencies():
    return WebhookIngressDependencies(
        verify_signature=verify_signature,
        get_square_webhook_signature_key=get_square_webhook_signature_key,
        get_square_webhook_notification_url=get_square_webhook_notification_url,
        get_webhook_event=get_webhook_event,
        get_order_processing_state=get_order_processing_state,
        reserve_order_processing=reserve_order_processing,
        clear_order_processing_reservation=clear_order_processing_reservation,
        create_webhook_event=create_webhook_event,
        record_webhook_event=record_webhook_event,
        dispatch_webhook_job=dispatch_webhook_job,
        set_webhook_event_status=set_webhook_event_status,
        get_or_create_last_synced_at=get_or_create_last_synced_at,
        search_changed_catalog_objects=search_changed_catalog_objects,
        get_latest_updated_at=get_latest_updated_at,
        summarize_changed_object=summarize_changed_object,
        update_last_synced_at=update_last_synced_at,
        get_square_environment_name=get_square_environment_name,
        get_merchant_context=get_merchant_context,
    )


@app.post("/webhook/square")
async def square_webhook(request: Request, background_tasks: BackgroundTasks):
    signature_header = request.headers.get("x-square-hmacsha256-signature", "")
    request_body = (await request.body()).decode("utf-8")

    response = handle_square_webhook_request(
        request_body=request_body,
        signature_header=signature_header,
        background_tasks=background_tasks,
        deps=_build_webhook_ingress_dependencies(),
    )
    return JSONResponse(content=response.body, status_code=response.status_code)
