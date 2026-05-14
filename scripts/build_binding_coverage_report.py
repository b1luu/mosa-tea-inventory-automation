import json
import sys

from app.binding_coverage_report import build_binding_coverage_report
from app.json_utils import to_jsonable


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.build_binding_coverage_report "
        "--environment sandbox|production --merchant-id MERCHANT_ID "
        "--location-id LOCATION_ID [--binding-version VERSION]"
    )


def _parse_args(argv):
    environment = None
    merchant_id = None
    location_id = None
    binding_version = None

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
        elif arg == "--binding-version":
            i += 1
            binding_version = int(argv[i]) if i < len(argv) else None
        else:
            raise ValueError(_usage())
        i += 1

    if environment not in {"sandbox", "production"} or not merchant_id or not location_id:
        raise ValueError(_usage())

    return environment, merchant_id, location_id, binding_version


def main():
    try:
        environment, merchant_id, location_id, binding_version = _parse_args(sys.argv[1:])
    except (ValueError, IndexError):
        print(_usage())
        return 1

    report = build_binding_coverage_report(
        environment,
        merchant_id,
        location_id,
        binding_version=binding_version,
    )
    print(json.dumps(to_jsonable(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
