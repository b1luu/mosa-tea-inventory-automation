import json

from app.sqs_worker import process_one_sqs_message


def main():
    result = process_one_sqs_message()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
