from datetime import datetime, timedelta, timezone

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
from app.square_errors import square_error_details


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


# Square rejects an adjustment whose occurred_at is more than 24 hours old.
# Keep an hour of room for retries.
OCCURRED_AT_MAX_AGE = timedelta(hours=23)


def _utcnow():
    return datetime.now(timezone.utc)


def _parse_rfc3339(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else None


def deterministic_occurred_at(order_summaries, *, now=None):
    """The adjustment timestamp: the latest order's Square created_at.

    The idempotency key depends only on the orders and their usage, so the
    request body must not change between attempts either. A retry after a
    successful write (the usage log or the state update raised) then sends the
    identical request, Square returns the original result, and the order ends
    applied with one deduction. A timestamp taken at processing time made the
    retry a different request under a used key, which Square refuses.

    Returns None (the plan then uses the current time, as before) when any
    order lacks a parseable created_at, or when the latest is in the future or
    older than OCCURRED_AT_MAX_AGE: Square rejects occurred_at older than 24
    hours, so orders recovered or replayed a day later still use now, and a
    retry after a successful write can still end failed for them.
    """
    now = now or _utcnow()
    stamps = [
        (_parse_rfc3339(summary.get("created_at")), summary.get("created_at"))
        for summary in order_summaries
    ]
    if not stamps or any(parsed is None for parsed, _ in stamps):
        return None
    latest, raw = max(stamps, key=lambda stamp: stamp[0])
    if latest > now or now - latest > OCCURRED_AT_MAX_AGE:
        return None
    return raw


def build_inventory_plan(order_summaries, *, skipped_orders=None):
    return build_inventory_plan_from_order_summaries(
        order_summaries,
        skipped_orders=skipped_orders,
        occurred_at=deterministic_occurred_at(order_summaries),
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
        return {
            "error": f"Square API error: {error}",
            "square_errors": square_error_details(error),
        }


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
