from square import Square
from square.environment import SquareEnvironment

from app.config import SQUARE_ACCESS_TOKEN

client = Square(
    environment=SquareEnvironment.SANDBOX,
    token=SQUARE_ACCESS_TOKEN,
)

