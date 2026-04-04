import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import oauth_state_db


class OAuthStateDbTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = oauth_state_db.DB_FILE
        oauth_state_db.DB_FILE = Path(self.temp_dir.name) / "oauth_state.db"

    def tearDown(self):
        oauth_state_db.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_create_and_consume_oauth_state(self):
        state = oauth_state_db.create_oauth_state("production")

        record = oauth_state_db.consume_oauth_state(state)

        self.assertEqual(record["environment"], "production")
        self.assertEqual(record["state"], state)

    def test_consume_oauth_state_rejects_reuse(self):
        state = oauth_state_db.create_oauth_state("production")

        self.assertIsNotNone(oauth_state_db.consume_oauth_state(state))
        self.assertIsNone(oauth_state_db.consume_oauth_state(state))

    def test_consume_oauth_state_rejects_expired_state(self):
        old_now = datetime.now(UTC) - timedelta(minutes=30)

        with patch("app.oauth_state_db._utcnow", return_value=old_now):
            state = oauth_state_db.create_oauth_state("production")

        self.assertIsNone(oauth_state_db.consume_oauth_state(state, max_age_seconds=60))


if __name__ == "__main__":
    unittest.main()
