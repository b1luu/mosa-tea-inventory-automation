import json
from uuid import uuid4


TARGET_DEFINITIONS = [
    {
        "key": "tea_base",
        "name": "Tea Base",
        "description": (
            "Internal dependency metadata for this drink's required tea base. "
            "Example values later: tgy, green, four_seasons, black."
        ),
    },
    {
        "key": "required_components",
        "name": "Required Components",
        "description": (
            "Internal dependency metadata for non-base components required to "
            "sell this item. Store a JSON array string later, for example "
            '[\"boba\", \"hun_kue\"].'
        ),
    },
]
TARGET_KEYS = {spec["key"] for spec in TARGET_DEFINITIONS}


def _definition_data(spec):
    # Keep Phase 0A simple: both values are plain strings on ITEM objects.
    return {
        "key": spec["key"],
        "name": spec["name"],
        "description": spec["description"],
        "type": "STRING",
        "allowed_object_types": ["ITEM"],
        "seller_visibility": "SELLER_VISIBILITY_HIDDEN",
        "app_visibility": "APP_VISIBILITY_HIDDEN",
        "string_config": {
            "enforce_uniqueness": False,
        },
    }


def _catalog_object_to_dict(catalog_object):
    return catalog_object.model_dump(by_alias=True, exclude_none=True)


def _normalized_definition(catalog_object):
    data = catalog_object.custom_attribute_definition_data
    string_config = data.string_config if data else None

    return {
        "key": data.key if data else None,
        "name": data.name if data else None,
        "description": data.description if data else None,
        "type": data.type if data else None,
        "allowed_object_types": sorted(data.allowed_object_types or []) if data else [],
        "seller_visibility": data.seller_visibility if data else None,
        "app_visibility": data.app_visibility if data else None,
        "string_config": {
            "enforce_uniqueness": (
                string_config.enforce_uniqueness if string_config else None
            )
        },
    }


def _definition_matches_spec(catalog_object, spec):
    current = _normalized_definition(catalog_object)
    expected = _definition_data(spec)
    expected["allowed_object_types"] = sorted(expected["allowed_object_types"])
    return current == expected


def _build_upsert_object(spec, existing_object=None):
    object_payload = {
        "id": existing_object.id if existing_object else f"#{spec['key']}",
        "type": "CUSTOM_ATTRIBUTE_DEFINITION",
        "custom_attribute_definition_data": _definition_data(spec),
    }

    if existing_object and existing_object.version is not None:
        object_payload["version"] = existing_object.version

    return object_payload


def _list_target_definitions(client):
    definitions_by_key = {}

    for catalog_object in client.catalog.list(types="CUSTOM_ATTRIBUTE_DEFINITION"):
        data = catalog_object.custom_attribute_definition_data
        if not data or not data.key:
            continue
        if data.key in TARGET_KEYS:
            definitions_by_key[data.key] = catalog_object

    return definitions_by_key


def _validate_existing_definition(existing_object, spec):
    data = existing_object.custom_attribute_definition_data
    if not data:
        raise ValueError(
            f"Catalog object {existing_object.id} is missing custom attribute definition data."
        )

    if data.type != "STRING":
        raise ValueError(
            f"Existing definition '{spec['key']}' has type '{data.type}'. "
            "This Phase 0A script expects STRING definitions."
        )


def _upsert_definition(client, spec, existing_object=None):
    action = "Updating" if existing_object else "Creating"
    print(f"\n{action} definition '{spec['key']}'...")

    response = client.catalog.object.upsert(
        idempotency_key=str(uuid4()),
        object=_build_upsert_object(spec, existing_object),
    )

    if not response.catalog_object:
        raise RuntimeError(
            f"Square did not return a catalog object for definition '{spec['key']}'."
        )

    print(
        json.dumps(
            _catalog_object_to_dict(response.catalog_object),
            indent=2,
        )
    )
    return response.catalog_object


def _retrieve_definition(client, object_id):
    response = client.catalog.object.get(object_id=object_id)
    if not response.object:
        raise RuntimeError(f"Square did not return catalog object '{object_id}'.")
    return response.object


def ensure_catalog_custom_attribute_definitions(client):
    # Start by finding any existing definitions with our target keys.
    existing_definitions = _list_target_definitions(client)
    verified_definitions = []

    print(
        "Existing matching definitions:",
        sorted(existing_definitions.keys()) if existing_definitions else "none",
    )

    for spec in TARGET_DEFINITIONS:
        existing_object = existing_definitions.get(spec["key"])

        if existing_object:
            _validate_existing_definition(existing_object, spec)

        if not existing_object:
            catalog_object = _upsert_definition(client, spec)
        elif _definition_matches_spec(existing_object, spec):
            print(f"\nDefinition '{spec['key']}' already matches the expected shape.")
            catalog_object = existing_object
        else:
            catalog_object = _upsert_definition(client, spec, existing_object)

        # Fetch the saved object again so we inspect the server's stored version.
        verified_definitions.append(_retrieve_definition(client, catalog_object.id))

    print("\nVerified definitions:")
    print(
        json.dumps(
            [_catalog_object_to_dict(item) for item in verified_definitions],
            indent=2,
        )
    )

    return verified_definitions


def format_api_error(error):
    lines = ["Square API error:"]
    lines.append(f"Status code: {error.status_code}")

    for entry in error.errors:
        detail = entry.detail or "No detail provided."
        lines.append(f"- {entry.code}: {detail}")

    if error.body:
        lines.append("Raw error body:")
        lines.append(json.dumps(error.body, indent=2, default=str))

    return "\n".join(lines)
