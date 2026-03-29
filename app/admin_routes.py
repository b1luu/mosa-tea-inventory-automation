from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.order_processing_db import get_order_processing_state, list_order_processing_rows
from app.order_processor import process_orders


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
    result = process_orders([order_id], apply_changes=True)
    processing_state_after = get_order_processing_state(order_id)
    return {
        "order_id": order_id,
        "current_processing_state": current_processing_state,
        "processing_state_after": processing_state_after,
        "inventory_response": result["inventory_response"],
        "skipped_orders": result["skipped_orders"],
        "skipped_line_items": result["skipped_line_items"],
    }
