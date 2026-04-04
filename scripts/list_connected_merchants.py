import json
import sys

from square.core.api_error import ApiError

from app.client import create_square_client_for_merchant
from app.json_utils import to_jsonable
from app.merchant_store import get_merchant_auth_record, list_merchant_contexts
from app.square_oauth import summarize_location


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.list_connected_merchants "
        "[--environment sandbox|production] [--status pending|active|revoked|disabled] "
        "[--verify-live]"
    )


def _parse_args(argv):
    environment = None
    status = None
    verify_live = False

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
        elif arg == "--status":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            status = argv[i].strip().lower()
            if status not in {"pending", "active", "revoked", "disabled"}:
                raise ValueError(_usage())
        elif arg == "--verify-live":
            verify_live = True
        else:
            raise ValueError(_usage())
        i += 1

    return environment, status, verify_live


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


def _verify_live_connection(environment, merchant_id):
    client = create_square_client_for_merchant(environment, merchant_id)
    response = client.locations.list()
    locations = list(response.locations or [])
    return {
        "verified": True,
        "location_count": len(locations),
        "locations": [summarize_location(location) for location in locations],
    }


def _build_report(environment=None, status=None, verify_live=False):
    contexts = list_merchant_contexts(status=status)
    if environment is not None:
        contexts = [
            context for context in contexts if context.environment == environment
        ]

    merchants = []
    for context in contexts:
        auth_record = get_merchant_auth_record(context.environment, context.merchant_id)
        merchant_report = {
            "environment": context.environment,
            "merchant_id": context.merchant_id,
            "status": context.status,
            "auth_mode": context.auth_mode,
            "display_name": context.display_name,
            "selected_location_id": context.location_id,
            "writes_enabled": context.writes_enabled,
            "binding_version": context.binding_version,
            "auth": _summarize_auth_record(auth_record),
        }

        if verify_live:
            try:
                merchant_report["live"] = _verify_live_connection(
                    context.environment,
                    context.merchant_id,
                )
            except (ApiError, ValueError) as error:
                merchant_report["live"] = {
                    "verified": False,
                    "error": str(error),
                }

        merchants.append(merchant_report)

    return {
        "summary": {
            "environment_filter": environment,
            "status_filter": status,
            "verify_live": verify_live,
            "merchant_count": len(merchants),
        },
        "merchants": merchants,
    }


def main():
    try:
        environment, status, verify_live = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    print(
        json.dumps(
            to_jsonable(
                _build_report(
                    environment=environment,
                    status=status,
                    verify_live=verify_live,
                )
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
