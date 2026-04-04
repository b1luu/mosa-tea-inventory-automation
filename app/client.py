from square import Square
from square.environment import SquareEnvironment

from app.config import get_square_access_token, get_square_environment_name
from app.merchant_store import get_merchant_access_token


def _resolve_square_access_token(access_token=None):
    # Preserve the current env-based flow, but allow callers to supply a
    # merchant-scoped token later when OAuth is added.
    return access_token if access_token is not None else get_square_access_token()


def _resolve_square_environment(environment_name=None):
    environment_name = (
        environment_name if environment_name is not None else get_square_environment_name()
    )
    environment = (
        SquareEnvironment.SANDBOX
        if environment_name == "sandbox"
        else SquareEnvironment.PRODUCTION
    )
    return environment


def create_square_client(access_token=None, environment_name=None):
    # Build one reusable SDK client for the rest of the app. Today this still
    # defaults to the env token, but the call site can now provide an explicit
    # token for an OAuth-authorized merchant.
    return Square(
        environment=_resolve_square_environment(environment_name),
        token=_resolve_square_access_token(access_token),
    )


def create_square_client_for_merchant(environment, merchant_id):
    access_token = get_merchant_access_token(environment, merchant_id)
    if not access_token:
        raise ValueError(
            f"No active Square access token found for merchant {merchant_id!r} "
            f"in environment {environment!r}."
        )

    return create_square_client(
        access_token=access_token,
        environment_name=environment,
    )
