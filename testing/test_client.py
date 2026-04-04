import unittest
from unittest.mock import patch

from square.environment import SquareEnvironment

from app.client import create_square_client_for_merchant


class ClientTests(unittest.TestCase):
    def test_create_square_client_for_merchant_uses_merchant_token_and_environment(self):
        captured = {}

        def fake_square(*, environment, token):
            captured["environment"] = environment
            captured["token"] = token
            return {"environment": environment, "token": token}

        with (
            patch("app.client.get_merchant_access_token", return_value="merchant-token"),
            patch("app.client.Square", side_effect=fake_square),
        ):
            client = create_square_client_for_merchant("production", "merchant-1")

        self.assertEqual(client["token"], "merchant-token")
        self.assertEqual(captured["environment"], SquareEnvironment.PRODUCTION)

    def test_create_square_client_for_merchant_raises_when_token_missing(self):
        with patch("app.client.get_merchant_access_token", return_value=None):
            with self.assertRaises(ValueError):
                create_square_client_for_merchant("production", "merchant-1")


if __name__ == "__main__":
    unittest.main()
