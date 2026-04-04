import json
import sys

from app.json_utils import to_jsonable
from app.merchant_store import enable_merchant_writes_if_ready


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.enable_merchant_writes "
        "--environment sandbox|production --merchant-id MERCHANT_ID"
    )


def _summarize_auth_record(auth_record):
    if not auth_record:
        return None

    return {
        "source": auth_record["source"],
        "token_type": auth_record["token_type"],
        "expires_at": auth_record["expires_at"],
        "short_lived": auth_record["short_lived"],
        "scopes": auth_record["scopes"],
        "has_refresh_token": bool(auth_record["refresh_token"]),
        "updated_at": auth_record["updated_at"],
    }


def _summarize_result(result):
    readiness = result["readiness"]
    merchant_context = readiness["merchant_context"]

    return {
        "enabled": result["enabled"],
        "readiness": {
            "merchant_context": merchant_context,
            "auth_record": _summarize_auth_record(readiness["auth_record"]),
            "active_binding": readiness["active_binding"],
            "ready": readiness["ready"],
            "reasons": readiness["reasons"],
        },
    }


def _parse_args(argv):
    environment = None
    merchant_id = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--environment":
            i += 1
            environment = argv[i].strip().lower() if i < len(argv) else None
        elif arg == "--merchant-id":
            i += 1
            merchant_id = argv[i].strip() if i < len(argv) else None
        else:
            raise ValueError(_usage())
        i += 1

    if environment not in {"sandbox", "production"} or not merchant_id:
        raise ValueError(_usage())

    return environment, merchant_id


def main():
    try:
        environment, merchant_id = _parse_args(sys.argv[1:])
    except (ValueError, IndexError):
        print(_usage())
        return 1

    result = enable_merchant_writes_if_ready(environment, merchant_id)
    print(json.dumps(to_jsonable(_summarize_result(result)), indent=2))
    return 0 if result["enabled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
