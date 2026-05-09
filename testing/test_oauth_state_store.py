import unittest
from unittest.mock import patch

from app import oauth_state_store


class OAuthStateStoreTests(unittest.TestCase):
    def test_uses_sqlite_backend_by_default(self):
        with patch(
            "app.oauth_state_store.get_oauth_state_store_mode",
            return_value="sqlite",
        ):
            with patch(
                "app.oauth_state_store.oauth_state_db.create_oauth_state",
                return_value="state-1",
            ) as mock_sqlite:
                state = oauth_state_store.create_oauth_state("sandbox")

        self.assertEqual(state, "state-1")
        mock_sqlite.assert_called_once_with("sandbox")

    def test_sqlite_consume_uses_sqlite_backend(self):
        with patch(
            "app.oauth_state_store.get_oauth_state_store_mode",
            return_value="sqlite",
        ):
            with patch(
                "app.oauth_state_store.oauth_state_db.consume_oauth_state",
                return_value={"state": "state-1", "environment": "sandbox"},
            ) as mock_sqlite:
                record = oauth_state_store.consume_oauth_state(
                    "state-1",
                    max_age_seconds=60,
                )

        self.assertEqual(record["environment"], "sandbox")
        mock_sqlite.assert_called_once_with("state-1", max_age_seconds=60)

    def test_uses_dynamodb_backend_when_configured(self):
        with patch(
            "app.oauth_state_store.get_oauth_state_store_mode",
            return_value="dynamodb",
        ):
            with patch(
                "app.oauth_state_store.oauth_state_dynamodb.consume_oauth_state",
                return_value={"state": "state-1", "environment": "production"},
            ) as mock_dynamodb:
                record = oauth_state_store.consume_oauth_state(
                    "state-1",
                    max_age_seconds=60,
                )

        self.assertEqual(record["state"], "state-1")
        mock_dynamodb.assert_called_once_with("state-1", max_age_seconds=60)

    def test_unsupported_store_mode_raises_value_error(self):
        with patch(
            "app.oauth_state_store.get_oauth_state_store_mode",
            return_value="memory",
        ):
            with self.assertRaisesRegex(
                ValueError,
                "Unsupported OAuth state store mode: memory",
            ):
                oauth_state_store.create_oauth_state("sandbox")


if __name__ == "__main__":
    unittest.main()
