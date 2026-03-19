from square.core.api_error import ApiError

from app.catalog_custom_attributes import (
    create_or_retrieve_required_components_definition,
    format_api_error,
    print_definition_response,
)
from app.client import create_square_client
from app.config import get_square_environment_name


def main():
    try:
        print("Square required_components custom attribute setup")
        print(f"Environment: {get_square_environment_name()}")

        # Build the Sandbox client from environment variables.
        client = create_square_client()

        # Create the definition if needed, or retrieve the current one if it already exists.
        response = create_or_retrieve_required_components_definition(client)

        # Show the final server response as formatted JSON.
        print_definition_response(response)

        print("\nSuccess. Verified 1 definition.")
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
