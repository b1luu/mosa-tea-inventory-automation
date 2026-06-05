import json
import sys

from square.core.api_error import ApiError

from app.script_client import create_square_client_from_args

# Simple catalog exploration script for Square Sandbox.
# This file creates an authenticated client, lists Catalog ITEM objects,
# converts each SDK model into plain dictionaries, and prints the result as JSON.
# It is meant for read-only inspection while learning the Square Catalog API.


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
    client, _ = create_square_client_from_args(sys.argv[1:])
    catalog_list(client)
