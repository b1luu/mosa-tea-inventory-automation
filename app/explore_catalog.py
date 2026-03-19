import json

from app.client import create_square_client
from square.core.api_error import ApiError


def catalog_list(client):
    try:
        # Ask Square for catalog objects of type ITEM.
        response = client.catalog.list(types="ITEM")

        # Build a plain Python list so we can print clean JSON.
        items = []
        for item in response:
            # Each Square model is converted to a regular dictionary first.
            items.append(item.model_dump(by_alias=True, exclude_none=True))

        # Print the final list once after all items have been collected.
        print(json.dumps(items, indent=2))

    except ApiError as error:
        # Print Square API errors without crashing the whole script.
        print(error)


if __name__ == "__main__":
    # Create the authenticated Square client, then run the catalog lookup.
    client = create_square_client()
    catalog_list(client)
