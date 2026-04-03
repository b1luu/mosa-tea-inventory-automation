from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.order_processing_store import (
    get_order_processing_state,
    list_order_processing_rows,
)
from app.webhook_worker import replay_order_job


admin_router = APIRouter()
TEMPLATE_FILE = Path("templates/admin/order_processing.html")


@admin_router.get("/admin/api/order-processing")
async def admin_order_processing_api():
    return list_order_processing_rows()


@admin_router.get("/admin/order-processing", response_class=HTMLResponse)
async def admin_order_processing_page():
    return HTMLResponse(content=TEMPLATE_FILE.read_text(encoding="utf-8"))


@admin_router.post("/admin/api/replay-order/{order_id}")
async def admin_replay_order(order_id: str):
    current_processing_state = get_order_processing_state(order_id)
    try:
        return replay_order_job(order_id)
    except RuntimeError as error:
        return {
            "order_id": order_id,
            "current_processing_state": current_processing_state,
            "processing_state_after": get_order_processing_state(order_id),
            "error": str(error),
            "inventory_response": None,
            "skipped_orders": [],
            "skipped_line_items": [],
        }
