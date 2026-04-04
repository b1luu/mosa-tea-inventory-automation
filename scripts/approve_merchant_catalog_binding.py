import json
import sys

from app.json_utils import to_jsonable
from app.merchant_store import (
    approve_catalog_binding,
    get_active_catalog_binding,
    get_merchant_context,
)


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.approve_merchant_catalog_binding "
        "--environment sandbox|production --merchant-id MERCHANT_ID "
        "--location-id LOCATION_ID --version VERSION"
    )


def _parse_args(argv):
    environment = None
    merchant_id = None
    location_id = None
    version = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--environment":
            i += 1
            environment = argv[i].strip().lower() if i < len(argv) else None
        elif arg == "--merchant-id":
            i += 1
            merchant_id = argv[i].strip() if i < len(argv) else None
        elif arg == "--location-id":
            i += 1
            location_id = argv[i].strip() if i < len(argv) else None
        elif arg == "--version":
            i += 1
            version = int(argv[i]) if i < len(argv) else None
        else:
            raise ValueError(_usage())
        i += 1

    if (
        environment not in {"sandbox", "production"}
        or not merchant_id
        or not location_id
        or version is None
    ):
        raise ValueError(_usage())

    return environment, merchant_id, location_id, version


def main():
    try:
        environment, merchant_id, location_id, version = _parse_args(sys.argv[1:])
    except (ValueError, IndexError):
        print(_usage())
        return 1

    approved = approve_catalog_binding(environment, merchant_id, location_id, version)
    context = get_merchant_context(environment, merchant_id)
    active_binding = get_active_catalog_binding(environment, merchant_id, location_id)

    print(
        json.dumps(
            to_jsonable(
                {
                    "approved": approved,
                    "merchant_id": merchant_id,
                    "environment": environment,
                    "location_id": location_id,
                    "version": version,
                    "binding_version_after": context.binding_version if context else None,
                    "active_binding": active_binding,
                }
            ),
            indent=2,
        )
    )
    return 0 if approved else 1


if __name__ == "__main__":
    raise SystemExit(main())
