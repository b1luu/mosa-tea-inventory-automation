import sys

from square.core.api_error import ApiError

from app.catalog_custom_attributes import (
    ensure_catalog_custom_attribute_definitions,
    format_api_error,
)
from app.client import create_square_client
from app.config import get_square_environment_name


def main():
    try:
        print("Square catalog custom attribute definition setup")
        print(f"Environment: {get_square_environment_name()}")

        # Build the Sandbox client from environment variables.
        client = create_square_client()

        # Create or update the two definitions, then fetch them back for inspection.
        definitions = ensure_catalog_custom_attribute_definitions(client)

        print(f"\nSuccess. Verified {len(definitions)} definition(s).")
        return 0
    except ValueError as error:
        print(f"Configuration error: {error}")
        return 1
    except ApiError as error:
        print(format_api_error(error))
        return 1
    except Exception as error:
        print(f"Unexpected error: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
