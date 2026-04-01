import json
import sys

from app.sqs_dispatcher import (
    change_webhook_job_visibility,
    delete_webhook_job,
    receive_webhook_jobs,
)


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.delete_sqs_job_by_order_id "
        "ORDER_ID [max_polls]"
    )


def _restore_visibility(messages):
    for message in messages:
        change_webhook_job_visibility(message["ReceiptHandle"], 0)


def main():
    if len(sys.argv) not in {2, 3}:
        print(_usage())
        return 1

    target_order_id = sys.argv[1]
    max_polls = int(sys.argv[2]) if len(sys.argv) == 3 else 5

    for _ in range(max_polls):
        messages = receive_webhook_jobs(max_number_of_messages=10, wait_time_seconds=1)
        if not messages:
            continue

        for message in messages:
            try:
                job = json.loads(message["Body"])
            except json.JSONDecodeError:
                continue

            if job.get("order_id") == target_order_id:
                delete_webhook_job(message["ReceiptHandle"])
                remaining_messages = [
                    candidate
                    for candidate in messages
                    if candidate["ReceiptHandle"] != message["ReceiptHandle"]
                ]
                _restore_visibility(remaining_messages)
                print(
                    json.dumps(
                        {
                            "order_id": target_order_id,
                            "message_id": message["MessageId"],
                            "deleted": True,
                        },
                        indent=2,
                    )
                )
                return 0

        _restore_visibility(messages)

    print(
        json.dumps(
            {
                "order_id": target_order_id,
                "deleted": False,
                "reason": "No matching queued job found within the polling limit.",
            },
            indent=2,
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
