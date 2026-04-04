from urllib.parse import urlencode

from square import Square
from square.environment import SquareEnvironment

from app.config import (
    get_square_oauth_client_id,
    get_square_oauth_client_secret,
    get_square_oauth_redirect_uri,
    get_square_oauth_scopes,
)


def _authorize_base_url(environment):
    if environment == "sandbox":
        return "https://connect.squareupsandbox.com/oauth2/authorize"
    return "https://connect.squareup.com/oauth2/authorize"


def _create_square_oauth_client(environment):
    return Square(
        environment=(
            SquareEnvironment.SANDBOX
            if environment == "sandbox"
            else SquareEnvironment.PRODUCTION
        )
    )


def _create_square_merchant_client(environment, access_token):
    return Square(
        environment=(
            SquareEnvironment.SANDBOX
            if environment == "sandbox"
            else SquareEnvironment.PRODUCTION
        ),
        token=access_token,
    )


def build_square_oauth_authorization_url(environment, state):
    query = urlencode(
        {
            "client_id": get_square_oauth_client_id(),
            "scope": " ".join(get_square_oauth_scopes()),
            "session": "false",
            "state": state,
            "redirect_uri": get_square_oauth_redirect_uri(),
        }
    )
    return f"{_authorize_base_url(environment)}?{query}"


def exchange_authorization_code(environment, code):
    client = _create_square_oauth_client(environment)
    return client.o_auth.obtain_token(
        client_id=get_square_oauth_client_id(),
        client_secret=get_square_oauth_client_secret(),
        grant_type="authorization_code",
        code=code,
        redirect_uri=get_square_oauth_redirect_uri(),
    )


def refresh_authorization_token(environment, refresh_token):
    client = _create_square_oauth_client(environment)
    return client.o_auth.obtain_token(
        client_id=get_square_oauth_client_id(),
        client_secret=get_square_oauth_client_secret(),
        grant_type="refresh_token",
        refresh_token=refresh_token,
    )


def retrieve_token_status(environment, access_token):
    client = _create_square_merchant_client(environment, access_token)
    return client.o_auth.retrieve_token_status()


def list_locations_for_merchant(environment, access_token):
    client = _create_square_merchant_client(environment, access_token)
    response = client.locations.list()
    return list(response.locations or [])


def summarize_location(location):
    return {
        "id": getattr(location, "id", None),
        "name": getattr(location, "name", None),
        "status": getattr(location, "status", None),
        "type": getattr(location, "type", None),
        "business_name": getattr(location, "business_name", None),
    }


def choose_default_location_id(locations):
    if not locations:
        return None

    active_locations = [
        location for location in locations if getattr(location, "status", None) == "ACTIVE"
    ]
    selected = active_locations[0] if active_locations else locations[0]
    return getattr(selected, "id", None)
