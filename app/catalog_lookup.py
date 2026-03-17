import sys,json 

from app.client import client
from square.core.api_error import ApiError

obj_id = sys.argv[1] if len(sys.argv) > 1 else None
if not obj_id:
    print("Usage: python catalog_lookup.py <OBJECT_ID>")
    exit()

res = client.catalog.retrieve_catalog_object(object_id=obj_id)

