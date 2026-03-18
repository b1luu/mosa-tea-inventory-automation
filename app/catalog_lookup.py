import sys,json 

from app.client import client
from square.core.api_error import ApiError


res = client.catalog.retrieve_catalog_object()

