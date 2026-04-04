import json
import sys

from app.json_utils import to_jsonable
from app.merchant_store import delete_merchant


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.delete_merchant "
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


def main():
    try:
        environment, merchant_id = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    result = delete_merchant(environment, merchant_id)
    print(json.dumps(to_jsonable(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
