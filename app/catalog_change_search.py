from app.client import create_square_client


SEARCH_OBJECT_TYPES = [
    "ITEM",
    "ITEM_VARIATION",
    "MODIFIER",
    "MODIFIER_LIST",
    "CATEGORY",
]


def search_changed_catalog_objects(begin_time):
    client = create_square_client()
    changed_objects = []
    cursor = None

    while True:
        response = client.catalog.search(
            cursor=cursor,
            object_types=SEARCH_OBJECT_TYPES,
            include_deleted_objects=True,
            begin_time=begin_time,
            limit=100,
        )

        changed_objects.extend(response.objects or [])

        if not response.cursor:
            break

        cursor = response.cursor

    return changed_objects


def summarize_changed_object(catalog_object):
    summary = {
        "type": catalog_object.type,
        "id": catalog_object.id,
        "updated_at": catalog_object.updated_at,
        "is_deleted": catalog_object.is_deleted,
    }

    if catalog_object.type == "ITEM":
        item_data = catalog_object.item_data
        summary["name"] = item_data.name if item_data else None

    if catalog_object.type == "ITEM_VARIATION":
        variation_data = catalog_object.item_variation_data
        summary["item_id"] = variation_data.item_id if variation_data else None
        summary["name"] = variation_data.name if variation_data else None

    if catalog_object.type == "MODIFIER":
        modifier_data = catalog_object.modifier_data
        summary["name"] = modifier_data.name if modifier_data else None

    if catalog_object.type == "CATEGORY":
        category_data = catalog_object.category_data
        summary["name"] = category_data.name if category_data else None

    return summary
