import json
from uuid import uuid4


REQUIRED_COMPONENTS_DEFINITION = {
    "key": "required_components",
    "name": "Required Components",
    "description": (
        "Hidden internal metadata for components required to sell this item. "
        "Example values later: boba, pistachio_cream_foam, "
        "brown_sugar_cream_foam, hun_kue."
    ),
}


def _definition_data():
    # Keep this first step simple: a hidden STRING attribute on ITEM objects.
    return {
        "key": REQUIRED_COMPONENTS_DEFINITION["key"],
        "name": REQUIRED_COMPONENTS_DEFINITION["name"],
        "description": REQUIRED_COMPONENTS_DEFINITION["description"],
        "type": "STRING",
        "allowed_object_types": ["ITEM"],
        "seller_visibility": "SELLER_VISIBILITY_HIDDEN",
        "app_visibility": "APP_VISIBILITY_HIDDEN",
        "string_config": {"enforce_uniqueness": False},
    }


def _model_to_dict(model):
    return model.model_dump(by_alias=True, exclude_none=True)


def _build_upsert_object():
    # New catalog objects use a client-generated temporary ID that starts with #.
    return {
        "id": "#required_components",
        "type": "CUSTOM_ATTRIBUTE_DEFINITION",
        "custom_attribute_definition_data": _definition_data(),
    }


def _find_existing_definition(client):
    # Look through existing custom attribute definitions and find our one target key.
    for catalog_object in client.catalog.list(types="CUSTOM_ATTRIBUTE_DEFINITION"):
        data = catalog_object.custom_attribute_definition_data
        if data and data.key == REQUIRED_COMPONENTS_DEFINITION["key"]:
            return catalog_object
    return None


def _validate_definition_shape(catalog_object):
    # Fail clearly only if the important schema is wrong.
    data = catalog_object.custom_attribute_definition_data
    if not data:
        raise ValueError(
            f"Catalog object {catalog_object.id} is missing custom attribute definition data."
        )

    if data.key != REQUIRED_COMPONENTS_DEFINITION["key"]:
        raise ValueError(
            "The existing definition does not use the expected key "
            "'required_components'."
        )

    if data.type != "STRING":
        raise ValueError(
            "The existing 'required_components' definition is not a STRING attribute."
        )

    if sorted(data.allowed_object_types or []) != ["ITEM"]:
        raise ValueError(
            "The existing 'required_components' definition is not limited to ITEM "
            "catalog objects."
        )

    if data.seller_visibility != "SELLER_VISIBILITY_HIDDEN":
        raise ValueError(
            "The existing 'required_components' definition is not hidden from seller UI."
        )

    if data.app_visibility != "APP_VISIBILITY_HIDDEN":
        raise ValueError(
            "The existing 'required_components' definition is not hidden from other apps."
        )


def _retrieve_definition_response(client, object_id):
    response = client.catalog.object.get(object_id=object_id)
    if not response.object:
        raise RuntimeError(f"Square did not return catalog object '{object_id}'.")
    return response


def create_or_retrieve_required_components_definition(client):
    # First check whether the definition already exists in the catalog.
    existing_definition = _find_existing_definition(client)

    if existing_definition:
        print("Found existing 'required_components' definition in Square.")
        _validate_definition_shape(existing_definition)
        response = _retrieve_definition_response(client, existing_definition.id)
    else:
        print("Definition not found. Creating 'required_components' in Square.")
        create_response = client.catalog.object.upsert(
            idempotency_key=str(uuid4()),
            object=_build_upsert_object(),
        )

        if not create_response.catalog_object:
            raise RuntimeError(
                "Square did not return a catalog object after creating "
                "'required_components'."
            )

        response = _retrieve_definition_response(
            client, create_response.catalog_object.id
        )

    _validate_definition_shape(response.object)
    return response


def print_definition_response(response):
    # Print the final API response in a readable JSON format for inspection.
    print(json.dumps(_model_to_dict(response), indent=2))


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
