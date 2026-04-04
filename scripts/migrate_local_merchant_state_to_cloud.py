import json
import sys
from pathlib import Path

from app import merchant_store_db, merchant_store_dynamodb
from app.json_utils import to_jsonable


def _usage():
    return (
        "Usage: ./.venv/bin/python -m scripts.migrate_local_merchant_state_to_cloud "
        "--environment sandbox|production --merchant-id MERCHANT_ID "
        "[--sqlite-db /path/to/merchant_store.db] [--skip-secret-sync]"
    )


def _parse_args(argv):
    environment = None
    merchant_id = None
    sqlite_db = None
    skip_secret_sync = False

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
        elif arg == "--sqlite-db":
            i += 1
            if i >= len(argv):
                raise ValueError(_usage())
            sqlite_db = Path(argv[i]).expanduser()
        elif arg == "--skip-secret-sync":
            skip_secret_sync = True
        else:
            raise ValueError(_usage())
        i += 1

    if not environment or not merchant_id:
        raise ValueError(_usage())

    return environment, merchant_id, sqlite_db, skip_secret_sync


def migrate_merchant_state(
    environment,
    merchant_id,
    *,
    sqlite_db=None,
    sync_secret=True,
):
    original_db_file = merchant_store_db.DB_FILE
    if sqlite_db is not None:
        merchant_store_db.DB_FILE = sqlite_db

    try:
        local_connection = merchant_store_db.get_merchant_connection(environment, merchant_id)
        if local_connection is None:
            raise ValueError(
                f"No local merchant connection found for merchant {merchant_id!r} "
                f"in environment {environment!r}."
            )

        local_auth = merchant_store_db.get_merchant_auth(environment, merchant_id)
        local_bindings = merchant_store_db.list_merchant_catalog_bindings(
            environment,
            merchant_id,
        )

        merchant_store_dynamodb.upsert_merchant_connection(
            environment,
            merchant_id,
            status=local_connection["status"],
            auth_mode=local_connection["auth_mode"],
            display_name=local_connection["display_name"],
            selected_location_id=local_connection["selected_location_id"],
            writes_enabled=local_connection["writes_enabled"],
            active_binding_version=local_connection["active_binding_version"],
        )

        if sync_secret and local_auth is not None:
            merchant_store_dynamodb.upsert_merchant_auth(
                environment,
                merchant_id,
                local_auth["access_token"],
                refresh_token=local_auth["refresh_token"],
                token_type=local_auth["token_type"],
                expires_at=local_auth["expires_at"],
                short_lived=local_auth["short_lived"],
                scopes=local_auth["scopes"],
                source=local_auth["source"],
            )

        for binding in local_bindings:
            merchant_store_dynamodb.upsert_merchant_catalog_binding(
                environment,
                merchant_id,
                binding["location_id"],
                binding["version"],
                binding["mapping"],
                status=binding["status"],
                notes=binding.get("notes"),
                approved_at=binding.get("approved_at"),
            )

        if local_connection["active_binding_version"] is not None:
            merchant_store_dynamodb.set_active_binding_version(
                environment,
                merchant_id,
                local_connection["active_binding_version"],
            )

        cloud_connection = merchant_store_dynamodb.get_merchant_connection(
            environment,
            merchant_id,
        )
        selected_location_id = cloud_connection.get("selected_location_id") if cloud_connection else None
        cloud_active_binding = (
            merchant_store_dynamodb.get_active_catalog_binding(
                environment,
                merchant_id,
                selected_location_id,
            )
            if selected_location_id
            else None
        )
        cloud_auth = (
            merchant_store_dynamodb.get_merchant_auth(environment, merchant_id)
            if sync_secret and local_auth is not None
            else None
        )

        return {
            "environment": environment,
            "merchant_id": merchant_id,
            "sqlite_db": str(merchant_store_db.DB_FILE),
            "secret_synced": bool(sync_secret and local_auth is not None),
            "local": {
                "merchant_connection_found": True,
                "auth_found": local_auth is not None,
                "binding_count": len(local_bindings),
                "active_binding_version": local_connection["active_binding_version"],
            },
            "cloud": {
                "merchant": cloud_connection,
                "auth": {
                    "found": cloud_auth is not None,
                    "source": cloud_auth.get("source") if cloud_auth else None,
                    "token_type": cloud_auth.get("token_type") if cloud_auth else None,
                    "expires_at": cloud_auth.get("expires_at") if cloud_auth else None,
                    "has_refresh_token": bool(cloud_auth and cloud_auth.get("refresh_token")),
                    "scope_count": len(cloud_auth.get("scopes", [])) if cloud_auth else 0,
                },
                "active_binding": cloud_active_binding,
                "binding_count": len(
                    merchant_store_dynamodb.list_merchant_catalog_bindings(
                        environment,
                        merchant_id,
                    )
                ),
            },
        }
    finally:
        merchant_store_db.DB_FILE = original_db_file


def main():
    try:
        environment, merchant_id, sqlite_db, skip_secret_sync = _parse_args(sys.argv[1:])
    except ValueError as error:
        print(error)
        return 1

    result = migrate_merchant_state(
        environment,
        merchant_id,
        sqlite_db=sqlite_db,
        sync_secret=not skip_secret_sync,
    )
    print(json.dumps(to_jsonable(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
