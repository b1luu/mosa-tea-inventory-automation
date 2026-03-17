import os

from dotenv import load_dotenv

load_dotenv()

SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN")

if not SQUARE_ACCESS_TOKEN:
    raise ValueError(
        "Missing required environment variable: SQUARE_ACCESS_TOKEN. "
        "Set it in your .env file before running the application."
    )