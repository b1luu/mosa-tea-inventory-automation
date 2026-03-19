import json 
from app.client import create_square_client

from square.core.api_error import ApiError
#returns a pager 
try:
    response = client.catalog.list(types="ITEM")
    print(json.dumps(response.mode_dump(by_alias=True, exclude_none=True), indent=2))
except ApiError as error:
    print(error)

