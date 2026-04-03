import json
import subprocess
import sys
import uuid

from square.core.api_error import ApiError

from app.client import create_square_client
from app.order_processing_store import get_order_processing_state
from scripts.inspect_order import summarize_order
from testing.create_live_test_order import (
    _build_order_payload,
    _load_scenarios,
)


def _usage():
    return (
        "Usage: ./.venv/bin/python -m testing.run_live_inventory_flow "
        "[--apply] <scenario_name>"
    )


def main():
    argv = sys.argv[1:]
    apply_changes = "--apply" in argv
    argv = [arg for arg in argv if arg != "--apply"]
    if len(argv) != 1:
        print(_usage())
        return 1

    scenario_name = argv[0]
    scenario_data = _load_scenarios()
    scenario = scenario_data["scenarios"].get(scenario_name)
    if not scenario:
        print(f"Unknown scenario: {scenario_name}")
        return 1

    client = create_square_client()
    order_payload = _build_order_payload(scenario_data["location_id"], scenario_name, scenario)
    response = client.orders.create(order=order_payload, idempotency_key=str(uuid.uuid4()))
    total_money = response.order.total_money
    try:
        payment = client.payments.create(
            source_id="cnon:card-nonce-ok",
            idempotency_key=str(uuid.uuid4()),
            order_id=response.order.id,
            location_id=scenario_data["location_id"],
            amount_money={"amount": total_money.amount, "currency": total_money.currency},
        )
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    refreshed_order = client.orders.get(order_id=response.order.id).order
    command = [sys.executable, "-m", "scripts.apply_inventory_adjustments"]
    if apply_changes:
        command.append("--apply")
    command.append(refreshed_order.id)
    apply_result = subprocess.run(command, capture_output=True, text=True, check=False)
    processing_state = get_order_processing_state(refreshed_order.id)

    print("scenario:")
    print(json.dumps({"name": scenario_name, "apply": apply_changes}, indent=2))
    print("created_order:")
    print(json.dumps(summarize_order(refreshed_order), indent=2))
    print("payment_summary:")
    print(json.dumps({"payment_id": payment.payment.id, "payment_status": payment.payment.status}, indent=2))
    print("apply_command:")
    print(" ".join(command))
    print("apply_output:")
    print(apply_result.stdout.strip())
    if apply_result.stderr.strip():
        print("apply_stderr:")
        print(apply_result.stderr.strip())
    print(
        "summary:",
        json.dumps(
            {
                "scenario": scenario_name,
                "mode": "apply" if apply_changes else "dry-run",
                "order_id": refreshed_order.id,
                "processing_state": processing_state,
                "apply_exit_code": apply_result.returncode,
            }
        ),
    )
    return apply_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
