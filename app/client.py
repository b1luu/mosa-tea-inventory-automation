from square import Square
from square.environment import SquareEnvironment

from app.config import get_square_access_token, get_square_environment_name


def _resolve_square_access_token(access_token=None):
    # Preserve the current env-based flow, but allow callers to supply a
    # merchant-scoped token later when OAuth is added.
    return access_token if access_token is not None else get_square_access_token()


def create_square_client(access_token=None):
    # Translate the simple environment name into Square's SDK enum.
    environment_name = get_square_environment_name()
    environment = (
        SquareEnvironment.SANDBOX
        if environment_name == "sandbox"
        else SquareEnvironment.PRODUCTION
    )

    # Build one reusable SDK client for the rest of the app. Today this still
    # defaults to the env token, but the call site can now provide an explicit
    # token for an OAuth-authorized merchant.
    return Square(
        environment=environment,
        token=_resolve_square_access_token(access_token),
    )
