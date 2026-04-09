from fastapi import APIRouter, Body, Depends, HTTPException

from app.manual_count_sync import (
    sync_manual_inventory_count,
    sync_manual_inventory_counts_batch,
)
from app.operator_auth import require_operator_access
from app.order_processing_store import (
    get_order_processing_state,
    list_order_processing_rows,
)
from app.webhook_event_store import list_webhook_events
from app.webhook_worker import replay_order_job


admin_router = APIRouter(dependencies=[Depends(require_operator_access)])


@admin_router.get("/admin/api/order-processing")
async def admin_order_processing_api():
    return list_order_processing_rows()


@admin_router.get("/admin/api/webhook-events")
async def admin_webhook_events_api():
    return list_webhook_events()


@admin_router.post("/admin/api/manual-count-sync")
def admin_manual_count_sync(body: dict = Body(...)):
    try:
        return sync_manual_inventory_count(
            environment=body["environment"],
            merchant_id=body["merchant_id"],
            location_id=body["location_id"],
            inventory_key=body["inventory_key"],
            counted_quantity=body["counted_quantity"],
            counted_unit=body.get("counted_unit", "bag"),
            apply_changes=bool(body.get("apply_changes", False)),
            source_reference=body.get("source_reference"),
        )
    except KeyError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required field: {error.args[0]}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@admin_router.post("/admin/api/manual-count-sync-batch")
def admin_manual_count_sync_batch(body: dict = Body(...)):
    try:
        rows = [
            {
                "inventory_key": row["inventory_key"],
                "counted_quantity": row["counted_quantity"],
                "counted_unit": row["counted_unit"],
                "source_reference": row.get("source_reference"),
            }
            for row in body["rows"]
        ]
        return sync_manual_inventory_counts_batch(
            environment=body["environment"],
            merchant_id=body["merchant_id"],
            location_id=body["location_id"],
            rows=rows,
            apply_changes=bool(body.get("apply_changes", False)),
        )
    except KeyError as error:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required field: {error.args[0]}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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
