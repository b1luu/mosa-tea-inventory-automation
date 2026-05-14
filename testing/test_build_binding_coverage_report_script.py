import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import build_binding_coverage_report


class BuildBindingCoverageReportScriptTests(unittest.TestCase):
    def test_parse_args_accepts_optional_binding_version(self):
        parsed = build_binding_coverage_report._parse_args(
            [
                "--environment",
                "production",
                "--merchant-id",
                "merchant-1",
                "--location-id",
                "LOC-1",
                "--binding-version",
                "7",
            ]
        )

        self.assertEqual(parsed, ("production", "merchant-1", "LOC-1", 7))

    def test_main_prints_report_json(self):
        report = {"summary": {"ready_for_approval": True}}
        stdout = io.StringIO()

        with (
            patch.object(
                build_binding_coverage_report,
                "build_binding_coverage_report",
                return_value=report,
            ),
            patch("sys.argv", ["script", "--environment", "sandbox", "--merchant-id", "m1", "--location-id", "L1"]),
            redirect_stdout(stdout),
        ):
            exit_code = build_binding_coverage_report.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), report)


if __name__ == "__main__":
    unittest.main()
