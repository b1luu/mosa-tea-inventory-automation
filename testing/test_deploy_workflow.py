"""Sandbox CD guardrails in .github/workflows/deploy-lambda.yml.

A push to main must only ever resolve to sandbox. These tests evaluate the
workflow's own ${{ }} expressions for push and workflow_dispatch events (a
small evaluator for the ==, !=, &&, || and quoting they use), and check that the
push guard runs before anything touches AWS. actionlint in CI checks syntax.
"""

import os
import re
import subprocess
import textwrap
import unittest
from pathlib import Path

WORKFLOW = Path(".github/workflows/deploy-lambda.yml")
TARGET_EXPRESSION = "github.event_name == 'push' && 'sandbox' || inputs.environment"

SANDBOX_VARS = {
    "AWS_REGION": "us-west-2",
    "WORKER_LAMBDA_FUNCTION_NAME": "mosa-tea-webhook-worker",
    # Set, as in the real repo. With it empty, `== 'production' && '' || vars.X`
    # looked right in tests and resolved to vars.X in a real production deploy.
    "LAMBDA_FUNCTION_NAME": "mosa-tea-webhook-worker",
    "WEBHOOK_INGRESS_LAMBDA_FUNCTION_NAME": "mosa-tea-webhook-ingress",
    "MANUAL_COUNT_SYNC_LAMBDA_FUNCTION_NAME": "mosa-tea-manual-count-sync",
    "OAUTH_LAMBDA_FUNCTION_NAME": "mosa-tea-oauth",
    "BINDING_COVERAGE_CHECK_LAMBDA_FUNCTION_NAME": "mosa-tea-binding-coverage-check",
    "OAUTH_REFRESH_LAMBDA_FUNCTION_NAME": "",
}
PROD_VARS = {
    f"PROD_{name}": f"{value}-prod"
    for name, value in SANDBOX_VARS.items()
    if name not in ("AWS_REGION", "LAMBDA_FUNCTION_NAME")
}
PROD_VARS["PROD_OAUTH_REFRESH_LAMBDA_FUNCTION_NAME"] = "mosa-tea-oauth-refresh-prod"
ALL_VARS = {**SANDBOX_VARS, **PROD_VARS}


def _evaluate(expression, *, event_name, environment_input, variables=None):
    """Evaluate a GitHub expression made of ==, !=, &&, ||, parentheses, quoted
    strings, github.event_name, inputs.environment and vars.NAME.

    && and || return an operand, and '' is falsy, as in GitHub expressions."""
    tokens = re.findall(r"'[^']*'|&&|\|\||==|!=|\(|\)|[A-Za-z_][A-Za-z0-9_.]*", expression)
    if "".join(tokens) != re.sub(r"\s+", "", expression):
        raise ValueError(f"Unsupported expression: {expression}")
    python = []
    for token in tokens:
        if token == "&&":
            python.append(" and ")
        elif token == "||":
            python.append(" or ")
        elif token in ("==", "!=", "(", ")"):
            python.append(f" {token} ")
        elif token.startswith("'"):
            python.append(repr(token[1:-1]))
        elif token == "github.event_name":
            python.append(repr(event_name))
        elif token == "inputs.environment":
            python.append(repr(environment_input))
        elif token.startswith("vars."):
            python.append(repr((ALL_VARS if variables is None else variables).get(token[len("vars."):], "")))
        else:
            raise ValueError(f"Unsupported token {token!r} in {expression}")
    return eval("".join(python), {"__builtins__": {}}, {})


def _workflow_text():
    return WORKFLOW.read_text()


def _expressions():
    """NAME -> expression for each `NAME: ${{ ... }}` line, plus the concurrency group."""
    text = _workflow_text()
    found = dict(re.findall(r"^\s{2}([A-Z_]+): \$\{\{ (.+) \}\}$", text, re.MULTILINE))
    (group,) = re.findall(r"^\s+group: deploy-lambda-functions-\$\{\{ (.+) \}\}$", text, re.MULTILINE)
    found["CONCURRENCY_GROUP"] = group
    return found


def _resolve(event_name, environment_input, variables=None):
    return {
        name: _evaluate(
            expression,
            event_name=event_name,
            environment_input=environment_input,
            variables=variables,
        )
        for name, expression in _expressions().items()
        if name not in ("AWS_REGION", "AWS_ROLE_TO_ASSUME")
    }


FUNCTION_NAMES = (
    "WORKER_LAMBDA_FUNCTION_NAME",
    "LEGACY_LAMBDA_FUNCTION_NAME",
    "WEBHOOK_INGRESS_LAMBDA_FUNCTION_NAME",
    "MANUAL_COUNT_SYNC_LAMBDA_FUNCTION_NAME",
    "OAUTH_LAMBDA_FUNCTION_NAME",
    "BINDING_COVERAGE_CHECK_LAMBDA_FUNCTION_NAME",
    "OAUTH_REFRESH_LAMBDA_FUNCTION_NAME",
)


class DeployWorkflowTargetTests(unittest.TestCase):
    def test_push_resolves_to_sandbox_everywhere(self):
        # A push carries no inputs; "production" here would be impossible, which
        # is exactly why it must still resolve to sandbox.
        for environment_input in ("", "production", "sandbox"):
            with self.subTest(environment_input=environment_input):
                resolved = _resolve("push", environment_input)
                self.assertEqual(resolved["TARGET_ENVIRONMENT"], "sandbox")
                self.assertEqual(resolved["CONCURRENCY_GROUP"], "sandbox")
                for name in FUNCTION_NAMES:
                    self.assertNotIn("prod", resolved[name], name)
                self.assertEqual(resolved["WORKER_LAMBDA_FUNCTION_NAME"], "mosa-tea-webhook-worker")

    def test_dispatch_resolves_to_the_chosen_environment(self):
        production = _resolve("workflow_dispatch", "production")
        self.assertEqual(production["TARGET_ENVIRONMENT"], "production")
        self.assertEqual(production["CONCURRENCY_GROUP"], "production")
        self.assertEqual(production["WORKER_LAMBDA_FUNCTION_NAME"], "mosa-tea-webhook-worker-prod")
        self.assertEqual(production["LEGACY_LAMBDA_FUNCTION_NAME"], "")

        sandbox = _resolve("workflow_dispatch", "sandbox")
        self.assertEqual(sandbox["TARGET_ENVIRONMENT"], "sandbox")
        self.assertEqual(sandbox["WORKER_LAMBDA_FUNCTION_NAME"], "mosa-tea-webhook-worker")

    def test_legacy_name_is_empty_in_production_whatever_the_variable_holds(self):
        for legacy_value in ("mosa-tea-webhook-worker", "anything-else", ""):
            with self.subTest(LAMBDA_FUNCTION_NAME=legacy_value):
                variables = dict(ALL_VARS, LAMBDA_FUNCTION_NAME=legacy_value)

                production = _resolve("workflow_dispatch", "production", variables)
                self.assertEqual(production["LEGACY_LAMBDA_FUNCTION_NAME"], "")

                for event_name, environment_input in (
                    ("push", ""),
                    ("push", "production"),
                    ("workflow_dispatch", "sandbox"),
                ):
                    sandbox = _resolve(event_name, environment_input, variables)
                    self.assertEqual(
                        sandbox["LEGACY_LAMBDA_FUNCTION_NAME"], legacy_value
                    )

    def test_no_expression_uses_an_empty_string_as_a_ternary_branch(self):
        # `cond && '' || x` always yields x, because '' is falsy.
        for name, expression in _expressions().items():
            with self.subTest(name=name):
                self.assertIsNone(
                    re.search(r"&&\s*(''|\"\")\s*\|\|", expression), expression
                )
        # Also every other line (if:, run:, step env), skipping comments.
        for line in _workflow_text().splitlines():
            if line.strip().startswith("#"):
                continue
            self.assertIsNone(re.search(r"&&\s*(''|\"\")\s*\|\|", line), line)

    def test_every_environment_choice_goes_through_the_target_expression(self):
        text = _workflow_text()
        for match in re.finditer(r"inputs\.environment", text):
            line = text[text.rfind("\n", 0, match.start()) + 1 : text.find("\n", match.end())]
            if "description" in line or line.strip().startswith("#"):
                continue
            self.assertIn(TARGET_EXPRESSION, line)


class DeployWorkflowPushGuardTests(unittest.TestCase):
    def _steps(self):
        return re.findall(r"^      - name: (.+)$", _workflow_text(), re.MULTILINE)

    def test_push_trigger_is_main_only_with_the_agreed_paths(self):
        text = _workflow_text()
        push = text[text.index("  push:") : text.index("  workflow_dispatch:")]
        self.assertIn("branches:\n      - main\n", push)
        for path in (
            "app/**",
            "server.py",
            "requirements.txt",
            "data/recipe_map.json",
            "data/inventory_item_map.json",
            ".github/workflows/deploy-lambda.yml",
        ):
            self.assertIn(f'- "{path}"', push)
        self.assertNotIn("data/**", push)

    def test_guard_is_the_first_step_and_runs_only_for_push(self):
        steps = self._steps()
        self.assertEqual(steps[0], "Refuse production from a push")
        text = _workflow_text()
        guard = text[text.index("- name: Refuse production from a push") : text.index("- name: Announce target environment")]
        self.assertIn("if: github.event_name == 'push'", guard)
        self.assertIn('if [ "${TARGET_ENVIRONMENT}" != "sandbox" ]', guard)
        self.assertIn("*prod*)", guard)
        for name in FUNCTION_NAMES:
            self.assertIn(name, guard)

    def test_guard_runs_before_credentials_and_deploy(self):
        steps = self._steps()
        guard = steps.index("Refuse production from a push")
        self.assertLess(guard, steps.index("Configure AWS credentials"))
        self.assertLess(guard, steps.index("Deploy Lambda package"))


def _step_script(step_name):
    """The run: | block of one workflow step, dedented."""
    text = _workflow_text()
    start = text.index(f"      - name: {step_name}\n")
    end = text.find("\n      - name: ", start + 1)
    step = text[start : end if end != -1 else len(text)]
    body = step[step.index("run: |\n") + len("run: |\n") :]
    return textwrap.dedent(body)


def _run_step(step_name, resolved, event_name):
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GITHUB_EVENT_NAME": event_name,
        **{name: value for name, value in resolved.items() if name != "CONCURRENCY_GROUP"},
    }
    return subprocess.run(
        ["bash", "-c", _step_script(step_name)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


class DeployWorkflowGuardScriptTests(unittest.TestCase):
    """Run the guard steps' own bash against the resolved environment."""

    PROD_GUARD = "Require production function names"
    PUSH_GUARD = "Refuse production from a push"

    def test_production_guard_runs_only_for_production_and_early(self):
        text = _workflow_text()
        step = text[text.index(f"- name: {self.PROD_GUARD}") :]
        step = step[: step.index("run: |")]
        self.assertIn("if: env.TARGET_ENVIRONMENT == 'production'", step)
        steps = re.findall(r"^      - name: (.+)$", text, re.MULTILINE)
        self.assertEqual(steps.index(self.PROD_GUARD), 1)

    def test_production_guard_passes_when_every_prod_var_is_set(self):
        # ALL_VARS has LAMBDA_FUNCTION_NAME set, as in the real repo (run #43).
        self.assertTrue(ALL_VARS["LAMBDA_FUNCTION_NAME"])
        result = _run_step(self.PROD_GUARD, _resolve("workflow_dispatch", "production"), "workflow_dispatch")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_production_guard_fails_when_the_legacy_name_leaks_through(self):
        resolved = dict(
            _resolve("workflow_dispatch", "production"),
            LEGACY_LAMBDA_FUNCTION_NAME="mosa-tea-webhook-worker",
        )
        result = _run_step(self.PROD_GUARD, resolved, "workflow_dispatch")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("LEGACY_LAMBDA_FUNCTION_NAME must be empty", result.stdout)

    def test_a_missing_prod_var_fails_the_production_guard(self):
        for missing in sorted(PROD_VARS):
            with self.subTest(missing=missing):
                variables = {name: value for name, value in ALL_VARS.items() if name != missing}
                resolved = _resolve("workflow_dispatch", "production", variables)
                # The quirk being guarded: the name silently falls back to sandbox.
                fallback = missing[len("PROD_") :]
                if SANDBOX_VARS.get(fallback):
                    self.assertEqual(resolved[fallback], SANDBOX_VARS[fallback])
                result = _run_step(self.PROD_GUARD, resolved, "workflow_dispatch")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("::error::", result.stdout)

    def test_push_guard_passes_for_sandbox_and_fails_on_a_prod_name(self):
        ok = _run_step(self.PUSH_GUARD, _resolve("push", ""), "push")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

        variables = dict(ALL_VARS, WEBHOOK_INGRESS_LAMBDA_FUNCTION_NAME="mosa-tea-webhook-ingress-prod")
        bad = _run_step(self.PUSH_GUARD, _resolve("push", "", variables), "push")
        self.assertEqual(bad.returncode, 1, bad.stdout)


if __name__ == "__main__":
    unittest.main()
