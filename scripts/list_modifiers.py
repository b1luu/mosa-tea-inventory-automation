import json

from square.core.api_error import ApiError

from app.client import create_square_client


def summarize_modifier(catalog_object):
    modifier_data = catalog_object.modifier_data
    return {
        "type": catalog_object.type,
        "id": catalog_object.id,
        "name": modifier_data.name if modifier_data else None,
        "modifier_list_id": modifier_data.modifier_list_id if modifier_data else None,
        "ordinal": modifier_data.ordinal if modifier_data else None,
        "updated_at": catalog_object.updated_at,
        "is_deleted": catalog_object.is_deleted,
    }


def summarize_modifier_list(catalog_object):
    modifier_list_data = catalog_object.modifier_list_data
    return {
        "type": catalog_object.type,
        "id": catalog_object.id,
        "name": modifier_list_data.name if modifier_list_data else None,
        "selection_type": (
            modifier_list_data.selection_type if modifier_list_data else None
        ),
        "modifiers": [
            {
                "id": modifier.id,
                "name": modifier.modifier_data.name if modifier.modifier_data else None,
                "ordinal": (
                    modifier.modifier_data.ordinal if modifier.modifier_data else None
                ),
            }
            for modifier in (modifier_list_data.modifiers or [])
        ] if modifier_list_data else [],
        "updated_at": catalog_object.updated_at,
        "is_deleted": catalog_object.is_deleted,
    }


def main():
    client = create_square_client()

    try:
        modifier_lists = [
            summarize_modifier_list(catalog_object)
            for catalog_object in client.catalog.list(types="MODIFIER_LIST")
        ]
        modifiers = [
            summarize_modifier(catalog_object)
            for catalog_object in client.catalog.list(types="MODIFIER")
        ]
    except ApiError as error:
        print(f"Square API error: {error}")
        return 1

    print("modifier_lists:")
    print(json.dumps(modifier_lists, indent=2))
    print("modifiers:")
    print(json.dumps(modifiers, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
