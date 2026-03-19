import json

from app.client import create_square_client
from square.core.api_error import ApiError

def catalog_list(client):
    try:
        response = client.catalog.list(types="ITEM")
        items = []
        for item in response:
            items.append(item.model_dump(by_alias=True, exclude_none=True))

            print(json.dumps(items, indent=2))

    except ApiError as error:
        print(error)

if __name__ == "__main__":
    client = create_square_client()
    catalog_list(client)

