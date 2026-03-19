from square import Square
from square.environment import SquareEnvironment

from app.config import get_square_access_token, get_square_environment_name


def create_square_client():
    # Translate the simple environment name into Square's SDK enum.
    environment_name = get_square_environment_name()
    environment = (
        SquareEnvironment.SANDBOX
        if environment_name == "sandbox"
        else SquareEnvironment.PRODUCTION
    )

    # Build one reusable SDK client for the rest of the script.
    return Square(
        environment=environment,
        token=get_square_access_token(),
    )
