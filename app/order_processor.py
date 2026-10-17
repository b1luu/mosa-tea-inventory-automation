from square.core.api_error import ApiError

from app.catalog_binding_resolver import resolve_inventory_variation_id
from app.client import create_square_client
from app.inventory_plan import (
    _build_adjustment_changes,
    _build_request_idempotency_key,
    build_inventory_plan_from_order_summaries,
)
from app.order_inventory_projection import is_log_only_inventory_key
from app.order_loader import load_order_summaries_for_processing


def _serialize_response_model(response):
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    return str(response)


def _resolve_combined_usage_for_binding(combined_usage, binding):
    if binding is None:
        return combined_usage

    resolved = []
    for usage in combined_usage:
        if is_log_only_inventory_key(usage["inventory_key"]):
            # No Square item to resolve; the usage log records it instead.
            resolved.append(usage)
            continue
        resolved.append(
            {
                **usage,
                "square_variation_id": resolve_inventory_variation_id(
                    usage["inventory_key"],
                    binding,
                ),
            }
        )
    return resolved


def resolve_inventory_request(plan, *, binding=None):
    if binding is None:
        return plan.inventory_request

    order_ids = [
        projected_order["order_id"] for projected_order in plan.projected_orders
    ]
    resolved_combined_usage = _resolve_combined_usage_for_binding(
        plan.combined_usage,
        binding,
    )
    changes = plan.inventory_request.get("changes", [])
    occurred_at = (
        changes[0]["adjustment"]["occurred_at"]
        if changes
        else None
    )

    return {
        "idempotency_key": _build_request_idempotency_key(
            order_ids,
            resolved_combined_usage,
        ),
        "changes": _build_adjustment_changes(
            order_ids,
            resolved_combined_usage,
            occurred_at,
        ),
        "ignore_unchanged_counts": plan.inventory_request.get(
            "ignore_unchanged_counts",
            True,
        ),
    }


def build_inventory_plan(order_summaries, *, skipped_orders=None):
    return build_inventory_plan_from_order_summaries(
        order_summaries,
        skipped_orders=skipped_orders,
    )


def apply_inventory_plan(plan, *, apply_changes=False, client=None, binding=None):
    inventory_request = resolve_inventory_request(plan, binding=binding)

    if not apply_changes:
        return None

    if not plan.can_apply:
        return {"error": plan.blocking_reason}

    if not inventory_request["changes"]:
        return {"message": "No inventory changes to apply."}

    # Defense-in-depth at the actual write site: never fall back to the env
    # token for batch_create_changes.
    if client is None:
        raise ValueError(
            "Applying inventory changes requires an explicit Square client; "
            "refusing to fall back to the environment token for a write."
        )
    try:
        response = client.inventory.batch_create_changes(**inventory_request)
        return _serialize_response_model(response)
    except ApiError as error:
        return {"error": f"Square API error: {error}"}


def process_order_summaries(
    order_summaries,
    *,
    skipped_orders=None,
    apply_changes=False,
    client=None,
    binding=None,
):
    plan = build_inventory_plan(order_summaries, skipped_orders=skipped_orders)
    inventory_request = resolve_inventory_request(plan, binding=binding)
    api_result = apply_inventory_plan(
        plan,
        apply_changes=apply_changes,
        client=client,
        binding=binding,
    )

    return {
        "mode": {"apply": apply_changes},
        **plan.to_dict(),
        "inventory_request": inventory_request,
        "inventory_response": api_result,
    }


def process_orders(
    order_ids,
    apply_changes=False,
    *,
    client=None,
    binding=None,
):
    if apply_changes and client is None:
        raise ValueError(
            "Applying inventory changes requires an explicit Square client; "
            "refusing to fall back to the environment token for a write."
        )
    # Reads/projection (apply_changes=False) may still use the env client.
    client = client or create_square_client()
    order_summaries, skipped_orders = load_order_summaries_for_processing(
        order_ids,
        client=client,
        binding=binding,
    )
    return process_order_summaries(
        order_summaries,
        skipped_orders=skipped_orders,
        apply_changes=apply_changes,
        client=client,
        binding=binding,
    )
