import unittest
from unittest.mock import patch

from app.script_client import create_square_client_from_args


class CreateSquareClientFromArgsTests(unittest.TestCase):
    def test_no_merchant_flag_uses_env_pat(self):
        with patch("app.script_client.create_square_client") as pat_client, patch(
            "app.script_client.create_square_client_for_merchant"
        ) as oauth_client:
            _, remaining = create_square_client_from_args([])
            pat_client.assert_called_once_with(environment_name=None)
            oauth_client.assert_not_called()
            self.assertEqual(remaining, [])

    def test_merchant_flag_uses_oauth_client_and_env_default(self):
        with patch(
            "app.script_client.create_square_client_for_merchant"
        ) as oauth_client, patch(
            "app.script_client.get_square_environment_name", return_value="sandbox"
        ):
            _, remaining = create_square_client_from_args(["--merchant", "ML123"])
            oauth_client.assert_called_once_with("sandbox", "ML123")
            self.assertEqual(remaining, [])

    def test_environment_flag_overrides_env_default(self):
        with patch(
            "app.script_client.create_square_client_for_merchant"
        ) as oauth_client:
            _, remaining = create_square_client_from_args(
                ["--merchant", "ML123", "--environment", "production"]
            )
            oauth_client.assert_called_once_with("production", "ML123")
            self.assertEqual(remaining, [])

    def test_environment_alone_without_merchant_uses_pat_with_override(self):
        with patch("app.script_client.create_square_client") as pat_client:
            _, remaining = create_square_client_from_args(
                ["--environment", "production"]
            )
            pat_client.assert_called_once_with(environment_name="production")
            self.assertEqual(remaining, [])

    def test_other_flags_are_preserved_in_remaining(self):
        with patch("app.script_client.create_square_client"):
            _, remaining = create_square_client_from_args(
                ["--apply", "--foo", "bar"]
            )
            self.assertEqual(remaining, ["--apply", "--foo", "bar"])

    def test_merchant_plus_other_flags_strips_only_merchant(self):
        with patch(
            "app.script_client.create_square_client_for_merchant"
        ), patch(
            "app.script_client.get_square_environment_name", return_value="sandbox"
        ):
            _, remaining = create_square_client_from_args(
                ["--merchant", "ML123", "--apply", "--foo"]
            )
            self.assertEqual(remaining, ["--apply", "--foo"])

    def test_flags_in_arbitrary_position(self):
        with patch(
            "app.script_client.create_square_client_for_merchant"
        ) as oauth_client:
            _, remaining = create_square_client_from_args(
                ["--apply", "--merchant", "ML123", "--foo", "--environment", "production"]
            )
            oauth_client.assert_called_once_with("production", "ML123")
            self.assertEqual(remaining, ["--apply", "--foo"])

    def test_merchant_without_value_raises(self):
        with self.assertRaises(ValueError) as ctx:
            create_square_client_from_args(["--merchant"])
        self.assertIn("--merchant", str(ctx.exception))

    def test_environment_without_value_raises(self):
        with self.assertRaises(ValueError) as ctx:
            create_square_client_from_args(["--environment"])
        self.assertIn("--environment", str(ctx.exception))

    def test_argv_input_not_mutated(self):
        original = ["--merchant", "ML123", "--apply"]
        snapshot = list(original)
        with patch(
            "app.script_client.create_square_client_for_merchant"
        ), patch(
            "app.script_client.get_square_environment_name", return_value="sandbox"
        ):
            create_square_client_from_args(original)
        self.assertEqual(original, snapshot, "input argv must not be mutated")


if __name__ == "__main__":
    unittest.main()
