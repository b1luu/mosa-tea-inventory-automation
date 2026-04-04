import json
import sys

from app.json_utils import to_jsonable
from app.merchant_store import (
    get_merchant_auth_record,
    get_merchant_context,
    get_merchant_write_readiness,
    list_catalog_bindings,
)


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.show_merchant_setup "
        "--environment sandbox|production --merchant-id MERCHANT_ID"
    )


def _parse_args(argv):
    environment = None
    merchant_id = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--environment":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            environment = argv[i].strip().lower()
            if environment not in {"sandbox", "production"}:
                raise ValueError(_usage())
        elif arg == "--merchant-id":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            merchant_id = argv[i].strip()
        else:
            raise ValueError(_usage())
        i += 1

    if not environment or not merchant_id:
        raise ValueError(_usage())

    return environment, merchant_id


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


def _summarize_context(context):
    if not context:
        return None

    return {
        "environment": context.environment,
        "merchant_id": context.merchant_id,
        "status": context.status,
        "auth_mode": context.auth_mode,
        "display_name": context.display_name,
        "selected_location_id": context.location_id,
        "writes_enabled": context.writes_enabled,
        "binding_version": context.binding_version,
    }


def build_report(environment, merchant_id):
    readiness = get_merchant_write_readiness(environment, merchant_id)
    context = get_merchant_context(environment, merchant_id)
    auth_record = get_merchant_auth_record(environment, merchant_id)
    location_id = context.location_id if context else None

    return {
        "merchant": _summarize_context(context),
        "auth": _summarize_auth_record(auth_record),
        "readiness": {
            "ready": readiness["ready"],
            "reasons": readiness["reasons"],
        },
        "active_binding": readiness["active_binding"],
        "bindings": list_catalog_bindings(
            environment,
            merchant_id,
            location_id=location_id,
        ),
    }


def main():
    try:
        environment, merchant_id = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    print(json.dumps(to_jsonable(build_report(environment, merchant_id)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
