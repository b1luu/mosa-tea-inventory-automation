import json
import sys
from pathlib import Path

from app.json_utils import to_jsonable
from app.merchant_store import upsert_catalog_binding


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.upsert_merchant_catalog_binding "
        "--environment sandbox|production --merchant-id MERCHANT_ID "
        "--location-id LOCATION_ID --version VERSION --mapping-file PATH "
        "[--notes NOTE]"
    )


def _parse_args(argv):
    environment = None
    merchant_id = None
    location_id = None
    version = None
    mapping_file = None
    notes = None

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
        elif arg == "--mapping-file":
            i += 1
            mapping_file = Path(argv[i]) if i < len(argv) else None
        elif arg == "--notes":
            i += 1
            notes = argv[i] if i < len(argv) else None
        else:
            raise ValueError(_usage())
        i += 1

    if (
        environment not in {"sandbox", "production"}
        or not merchant_id
        or not location_id
        or version is None
        or mapping_file is None
    ):
        raise ValueError(_usage())

    return environment, merchant_id, location_id, version, mapping_file, notes


def main():
    try:
        environment, merchant_id, location_id, version, mapping_file, notes = _parse_args(
            sys.argv[1:]
        )
    except (ValueError, IndexError):
        print(_usage())
        return 1

    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    binding = upsert_catalog_binding(
        environment,
        merchant_id,
        location_id,
        version,
        mapping,
        notes=notes,
    )
    print(json.dumps(to_jsonable(binding), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
