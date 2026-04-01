import tempfile
import unittest
from pathlib import Path

from scripts.reset_runtime_state import reset_runtime_state


class ResetRuntimeStateTests(unittest.TestCase):
    def test_removes_existing_runtime_files_and_reports_missing_ones(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            existing = root / "order_processing.db"
            existing.write_text("state", encoding="utf-8")
            missing = root / "webhook_events.db"

            result = reset_runtime_state([existing, missing])

            self.assertFalse(existing.exists())

        self.assertEqual(result["removed"], [str(existing)])
        self.assertEqual(result["missing"], [str(missing)])
