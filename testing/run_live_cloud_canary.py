import json
import sys
import time
import uuid
from decimal import Decimal

from boto3.dynamodb.conditions import Attr
from square.core.api_error import ApiError

from app.client import create_square_client
from app.config import (
    get_aws_region,
    get_dynamodb_order_processing_table_name,
    get_dynamodb_webhook_event_table_name,
)
from app.json_utils import to_jsonable
from scripts.inspect_inventory_count import (
    DEFAULT_STATES,
    _resolve_target,
    build_projected_adjustment_summary,
    summarize_inventory_counts,
)
from scripts.inspect_order import summarize_order
from testing.create_live_test_order import _build_order_payload, _load_scenarios
from testing.order_projection_utils import project_order_summary


DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_POLL_SECONDS = 3


def _status_line(message, **fields):
    parts = [message]
    for key, value in fields.items():
        parts.append(f"{key}={json.dumps(to_jsonable(value), sort_keys=True)}")
    return " | ".join(parts)


def _emit_status(message, **fields):
    print(_status_line(message, **fields), file=sys.stderr, flush=True)


def _usage():
    return (
        "Usage: ./.venv/bin/python -m testing.run_live_cloud_canary "
        "[--timeout-seconds N] [--poll-seconds N] <scenario_name>"
    )


def _parse_args(argv):
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS
    poll_seconds = DEFAULT_POLL_SECONDS

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--timeout-seconds":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            timeout_seconds = int(argv[i])
        elif arg == "--poll-seconds":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            poll_seconds = float(argv[i])
        else:
            break
        i += 1

    remaining = argv[i:]
    if len(remaining) != 1:
        raise ValueError(_usage())

    return timeout_seconds, poll_seconds, remaining[0]


def _quantized_decimal(value):
    return Decimal(str(value)).quantize(Decimal("0.00001"))


def _normalize_usage_by_inventory_key(combined_usage):
    return {
        usage["inventory_key"]: _quantized_decimal(usage["total_amount"])
        for usage in combined_usage
    }


def _create_dynamodb_resource():
    import boto3

    return boto3.resource("dynamodb", region_name=get_aws_region())


def _get_order_processing_row(order_id):
    table = _create_dynamodb_resource().Table(get_dynamodb_order_processing_table_name())
    response = table.get_item(
        Key={"square_order_id": order_id},
        ConsistentRead=True,
    )
    return response.get("Item")


def _list_webhook_events_for_order(order_id):
    table = _create_dynamodb_resource().Table(get_dynamodb_webhook_event_table_name())
    scan_kwargs = {
        "FilterExpression": Attr("order_id").eq(order_id),
        "ConsistentRead": True,
    }

    response = table.scan(**scan_kwargs)
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.scan(
            ExclusiveStartKey=response["LastEvaluatedKey"],
            **scan_kwargs,
        )
        items.extend(response.get("Items", []))

    items.sort(key=lambda item: item.get("received_at", ""))
    return items


def _summarize_webhook_events(events):
    status_counts = {}
    for event in events:
        status = event.get("status")
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "total": len(events),
        "status_counts": status_counts,
        "processed_count": status_counts.get("processed", 0),
        "failed_count": status_counts.get("failed", 0),
    }


def _pipeline_has_terminal_failure(order_row, event_summary):
    if not order_row:
        return False
    if order_row.get("processing_state") in {"failed", "blocked"}:
        return True
    return event_summary["failed_count"] > 0


def _pipeline_is_settled(order_row, event_summary):
    if not order_row:
        return False
    return (
        order_row.get("processing_state") == "applied"
        and event_summary["processed_count"] == 1
        and event_summary["failed_count"] == 0
    )


def _fetch_inventory_counts(client, targets, location_id):
    return list(
        client.inventory.batch_get_counts(
            catalog_object_ids=[target["catalog_object_id"] for target in targets],
            location_ids=[location_id],
            states=list(DEFAULT_STATES),
        )
    )


def _build_inventory_summary_by_key(
    targets,
    counts,
    location_id,
    combined_usage=None,
    source=None,
):
    summaries = {}
    for target in targets:
        target_counts = [
            count
            for count in counts
            if getattr(count, "catalog_object_id", None) == target["catalog_object_id"]
        ]
        projected_adjustment = None
        base_summary = summarize_inventory_counts(target, target_counts, location_id)
        if combined_usage is not None:
            projected_adjustment = build_projected_adjustment_summary(
                target,
                combined_usage,
                base_summary,
                source,
            )
        summaries[target["inventory_key"]] = summarize_inventory_counts(
            target,
            target_counts,
            location_id,
            projected_adjustment=projected_adjustment,
        )
    return summaries


def _inventory_mismatches(before_summaries, after_summaries):
    mismatches = []
    for inventory_key, before_summary in before_summaries.items():
        projected_adjustment = before_summary.get("projected_adjustment")
        if not projected_adjustment:
            continue

        after_summary = after_summaries[inventory_key]
        expected_after = projected_adjustment["after"]
        actual_after = {
            "in_stock_quantity": _quantized_decimal(after_summary["in_stock_quantity"]),
            "waste_quantity": _quantized_decimal(after_summary["waste_quantity"]),
        }

        if actual_after != expected_after:
            mismatches.append(
                {
                    "inventory_key": inventory_key,
                    "expected_after": expected_after,
                    "actual_after": actual_after,
                }
            )
    return mismatches


def _wait_for_square_order_completed(
    client,
    order_id,
    timeout_seconds,
    poll_seconds,
    status_callback=None,
):
    deadline = time.time() + timeout_seconds
    last_order = None
    attempt = 0

    while time.time() <= deadline:
        attempt += 1
        response = client.orders.get(order_id=order_id)
        last_order = response.order
        if last_order and last_order.state == "COMPLETED":
            return last_order
        if status_callback:
            status_callback(
                "waiting_for_square_order_completion",
                attempt=attempt,
                order_id=order_id,
                current_state=getattr(last_order, "state", None),
                elapsed_seconds=round(timeout_seconds - max(deadline - time.time(), 0), 2),
            )
        time.sleep(poll_seconds)

    raise RuntimeError(
        f"Timed out waiting for Square order '{order_id}' to reach COMPLETED. "
        f"Last state: {getattr(last_order, 'state', None)!r}."
    )


def _wait_for_pipeline_settlement(
    order_id,
    timeout_seconds,
    poll_seconds,
    status_callback=None,
):
    deadline = time.time() + timeout_seconds
    last_snapshot = None
    attempt = 0

    while time.time() <= deadline:
        attempt += 1
        order_row = _get_order_processing_row(order_id)
        events = _list_webhook_events_for_order(order_id)
        event_summary = _summarize_webhook_events(events)
        last_snapshot = {
            "order_processing": order_row,
            "webhook_events": events,
            "webhook_event_summary": event_summary,
        }

        if _pipeline_is_settled(order_row, event_summary):
            return last_snapshot
        if _pipeline_has_terminal_failure(order_row, event_summary):
            raise RuntimeError(
                f"Webhook pipeline reached a failure state for order '{order_id}'."
            )
        if status_callback:
            status_callback(
                "waiting_for_aws_pipeline",
                attempt=attempt,
                order_id=order_id,
                processing_state=(order_row or {}).get("processing_state"),
                processed_count=event_summary["processed_count"],
                failed_count=event_summary["failed_count"],
                total_events=event_summary["total"],
                elapsed_seconds=round(timeout_seconds - max(deadline - time.time(), 0), 2),
            )

        time.sleep(poll_seconds)

    raise RuntimeError(
        f"Timed out waiting for AWS pipeline settlement for order '{order_id}'. "
        f"Last snapshot: {json.dumps(to_jsonable(last_snapshot), indent=2)}"
    )


def _wait_for_inventory_counts(
    client,
    targets,
    location_id,
    before_summaries,
    timeout_seconds,
    poll_seconds,
    status_callback=None,
):
    deadline = time.time() + timeout_seconds
    last_mismatches = None
    attempt = 0

    while time.time() <= deadline:
        attempt += 1
        counts = _fetch_inventory_counts(client, targets, location_id)
        after_summaries = _build_inventory_summary_by_key(
            targets,
            counts,
            location_id,
        )
        last_mismatches = _inventory_mismatches(before_summaries, after_summaries)
        if not last_mismatches:
            return after_summaries
        if status_callback:
            status_callback(
                "waiting_for_inventory_counts",
                attempt=attempt,
                location_id=location_id,
                mismatch_count=len(last_mismatches),
                sample_mismatch=last_mismatches[0],
                elapsed_seconds=round(timeout_seconds - max(deadline - time.time(), 0), 2),
            )
        time.sleep(poll_seconds)

    raise RuntimeError(
        "Timed out waiting for live Square inventory counts to match the projected "
        f"adjustment. Last mismatches: {json.dumps(to_jsonable(last_mismatches), indent=2)}"
    )


def _create_and_pay_order(client, location_id, scenario_name, scenario):
    order_payload = _build_order_payload(location_id, scenario_name, scenario)
    order_response = client.orders.create(
        order=order_payload,
        idempotency_key=str(uuid.uuid4()),
    )
    if not order_response.order:
        raise RuntimeError("Order creation did not return an order.")

    total_money = getattr(order_response.order, "total_money", None)
    if not total_money or total_money.amount is None:
        raise RuntimeError("Created order did not return total_money; cannot create payment.")

    payment_response = client.payments.create(
        source_id="cnon:card-nonce-ok",
        idempotency_key=str(uuid.uuid4()),
        order_id=order_response.order.id,
        location_id=location_id,
        amount_money={
            "amount": total_money.amount,
            "currency": total_money.currency,
        },
    )
    return order_payload, order_response.order, payment_response.payment


def main():
    try:
        timeout_seconds, poll_seconds, scenario_name = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    scenario_data = _load_scenarios()
    location_id = scenario_data["location_id"]
    scenario = scenario_data.get("scenarios", {}).get(scenario_name)
    if not scenario:
        print(f"Unknown scenario: {scenario_name}")
        print(_usage())
        return 1

    scenario_order_payload = _build_order_payload(location_id, scenario_name, scenario)
    scenario_projected_line_items, scenario_combined_usage = project_order_summary(
        {"line_items": scenario_order_payload["line_items"]}
    )
    targets = [
        _resolve_target(inventory_key=usage["inventory_key"])
        for usage in scenario_combined_usage
    ]

    client = create_square_client()
    try:
        _emit_status(
            "canary_started",
            scenario_name=scenario_name,
            location_id=location_id,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        _emit_status("fetching_inventory_before", target_count=len(targets))
        before_counts = _fetch_inventory_counts(client, targets, location_id)
        before_summaries = _build_inventory_summary_by_key(
            targets,
            before_counts,
            location_id,
            combined_usage=scenario_combined_usage,
            source={"kind": "scenario", "name": scenario_name},
        )

        _emit_status("creating_and_paying_order", scenario_name=scenario_name)
        order_payload, created_order, payment = _create_and_pay_order(
            client,
            location_id,
            scenario_name,
            scenario,
        )
        _emit_status(
            "order_created",
            order_id=created_order.id,
            payment_id=payment.id if payment else None,
            payment_status=payment.status if payment else None,
        )
        completed_order = _wait_for_square_order_completed(
            client,
            created_order.id,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            status_callback=_emit_status,
        )
        _emit_status(
            "square_order_completed",
            order_id=completed_order.id,
            state=completed_order.state,
        )
        live_order_summary = summarize_order(completed_order)
        live_projected_line_items, live_combined_usage = project_order_summary(
            live_order_summary
        )

        if _normalize_usage_by_inventory_key(
            scenario_combined_usage
        ) != _normalize_usage_by_inventory_key(live_combined_usage):
            raise RuntimeError(
                "Live Square order projection did not match the scenario projection."
            )

        pipeline_snapshot = _wait_for_pipeline_settlement(
            completed_order.id,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            status_callback=_emit_status,
        )
        _emit_status(
            "aws_pipeline_settled",
            order_id=completed_order.id,
            processing_state=(pipeline_snapshot["order_processing"] or {}).get(
                "processing_state"
            ),
            webhook_event_summary=pipeline_snapshot["webhook_event_summary"],
        )
        after_summaries = _wait_for_inventory_counts(
            client,
            targets,
            location_id,
            before_summaries,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            status_callback=_emit_status,
        )
        _emit_status(
            "inventory_counts_settled",
            inventory_keys=sorted(after_summaries.keys()),
        )
    except (ApiError, RuntimeError) as error:
        print(f"canary_error: {error}")
        return 1

    result = {
        "scenario": {
            "name": scenario_name,
            "location_id": location_id,
            "timeout_seconds": timeout_seconds,
            "poll_seconds": poll_seconds,
        },
        "order_payload": order_payload,
        "created_order": summarize_order(created_order),
        "payment": {
            "id": payment.id if payment else None,
            "status": payment.status if payment else None,
        },
        "completed_order": live_order_summary,
        "projection": {
            "scenario_projected_line_items": scenario_projected_line_items,
            "scenario_combined_usage": scenario_combined_usage,
            "live_projected_line_items": live_projected_line_items,
            "live_combined_usage": live_combined_usage,
        },
        "inventory_before": before_summaries,
        "aws_pipeline": pipeline_snapshot,
        "inventory_after": after_summaries,
        "success": True,
    }

    _emit_status("canary_complete", order_id=created_order.id, success=True)
    print(json.dumps(to_jsonable(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
