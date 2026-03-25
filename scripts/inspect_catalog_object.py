import json
import sys

from square.core.api_error import ApiError

from app.client import create_square_client


def summarize_catalog_object(catalog_object):
    summary = {
        "type": catalog_object.type,
        "id": catalog_object.id,
        "updated_at": catalog_object.updated_at,
        "is_deleted": catalog_object.is_deleted,
    }

    if catalog_object.type == "MODIFIER":
        modifier_data = catalog_object.modifier_data
        summary["name"] = modifier_data.name if modifier_data else None
        summary["modifier_list_id"] = (
            modifier_data.modifier_list_id if modifier_data else None
        )
        summary["ordinal"] = modifier_data.ordinal if modifier_data else None
        summary["location_overrides"] = [
            {
                "location_id": override.location_id,
                "sold_out": override.sold_out,
            }
            for override in (modifier_data.location_overrides or [])
        ] if modifier_data else []

    elif catalog_object.type == "MODIFIER_LIST":
        modifier_list_data = catalog_object.modifier_list_data
        summary["name"] = modifier_list_data.name if modifier_list_data else None
        summary["selection_type"] = (
            modifier_list_data.selection_type if modifier_list_data else None
        )
        summary["modifiers"] = [
            {
                "id": modifier.id,
                "name": modifier.name,
                "ordinal": modifier.ordinal,
            }
            for modifier in (modifier_list_data.modifiers or [])
        ] if modifier_list_data else []

    elif catalog_object.type == "ITEM":
        item_data = catalog_object.item_data
        summary["name"] = item_data.name if item_data else None

    elif catalog_object.type == "ITEM_VARIATION":
        variation_data = catalog_object.item_variation_data
        summary["item_id"] = variation_data.item_id if variation_data else None
        summary["name"] = variation_data.name if variation_data else None

    elif catalog_object.type == "CATEGORY":
        category_data = catalog_object.category_data
        summary["name"] = category_data.name if category_data else None

    return summary


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: ./.venv/bin/python -m scripts.inspect_catalog_object "
            "<catalog_object_id> [<catalog_object_id> ...]"
        )
        return 1

    client = create_square_client()
    summaries = []

    for object_id in sys.argv[1:]:
        try:
            response = client.catalog.object.get(object_id=object_id)
        except ApiError as error:
            summaries.append(
                {
                    "id": object_id,
                    "error": f"Square API error: {error}",
                }
            )
            continue

        if not response.object:
            summaries.append(
                {
                    "id": object_id,
                    "error": "Catalog object not found",
                }
            )
            continue

        summaries.append(summarize_catalog_object(response.object))

    print(json.dumps(summaries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
