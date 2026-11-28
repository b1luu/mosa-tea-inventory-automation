import re
import unittest
from pathlib import Path


INFRA_DIR = Path(__file__).resolve().parent.parent / "infra"

ENV_SPECIFIC = re.compile(r"\$\{(local\.name_suffix|var\.environment_name)\}")


def _names(resource_type, attribute):
    """[(address, expression)] for every resource_type block in infra/*.tf.
    glob("*.tf") never matches *.tfvars."""
    found = []
    for tf in sorted(INFRA_DIR.glob("*.tf")):
        for block in re.finditer(
            rf'resource "{resource_type}" "(\w+)" \{{(.*?)\n\}}', tf.read_text(), re.S
        ):
            value = re.search(rf"^\s*{attribute}\s*=\s*(.+)$", block.group(2), re.M)
            found.append((f"{tf.name}: {resource_type}.{block.group(1)}",
                          value.group(1).strip() if value else ""))
    return found


def _raw_count(resource_type):
    """Count of resource_type declarations in infra/*.tf, however the block is
    formatted, so a block the lazy regex in _names() misses is noticed."""
    return sum(
        len(re.findall(rf'^\s*resource\s+"{resource_type}"', tf.read_text(), re.M))
        for tf in INFRA_DIR.glob("*.tf")
    )


class EnvScopedNameTests(unittest.TestCase):
    # Sandbox and production share one AWS account, and rule and alarm names are
    # account-unique upserts. A name built only from project_name makes both
    # workspaces fight over one physical resource.

    def test_every_event_rule_name_is_environment_scoped(self):
        rules = _names("aws_cloudwatch_event_rule", "name")
        self.assertGreaterEqual(len(rules), 2)
        self.assertEqual(len(rules), _raw_count("aws_cloudwatch_event_rule"))
        for address, expression in rules:
            with self.subTest(address=address):
                self.assertRegex(expression, ENV_SPECIFIC)

    def test_every_alarm_name_is_environment_scoped(self):
        alarms = _names("aws_cloudwatch_metric_alarm", "alarm_name")
        self.assertGreaterEqual(len(alarms), 5)
        self.assertEqual(len(alarms), _raw_count("aws_cloudwatch_metric_alarm"))
        for address, expression in alarms:
            with self.subTest(address=address):
                self.assertRegex(expression, ENV_SPECIFIC)

    def test_name_suffix_differs_per_environment(self):
        locals_tf = (INFRA_DIR / "locals.tf").read_text()
        line = re.search(r"^\s*name_suffix\s*=\s*(.+)$", locals_tf, re.M).group(1)
        self.assertIn('"-prod"', line)
        self.assertIn('"-sandbox"', line)


if __name__ == "__main__":
    unittest.main()
