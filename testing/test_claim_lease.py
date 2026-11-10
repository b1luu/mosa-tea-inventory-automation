import re
import unittest
from pathlib import Path

from app.order_processing_db import CLAIM_LEASE_SECONDS


INFRA_DIR = Path(__file__).resolve().parent.parent / "infra"


TIMING_VARIABLES = (
    "lambda_timeout_seconds",
    "webhook_queue_visibility_timeout_seconds",
    "webhook_queue_max_receive_count",
)


def _configured_timings():
    """{source: {variable: value}} from variables.tf defaults, then each local
    .tfvars (gitignored, so only present on a deploying machine) with its
    overrides applied on top."""
    variables = (INFRA_DIR / "variables.tf").read_text()
    defaults = {}
    for name in TIMING_VARIABLES:
        block = re.search(rf'variable "{name}" \{{(.*?)\n\}}', variables, re.S)
        defaults[name] = int(re.search(r"default\s*=\s*(\d+)", block.group(1)).group(1))

    timings = {"variables.tf": defaults}
    for tfvars in sorted(INFRA_DIR.glob("*.tfvars")):
        text = tfvars.read_text()
        merged = dict(defaults)
        for name in TIMING_VARIABLES:
            override = re.search(rf"^\s*{name}\s*=\s*(\d+)", text, re.M)
            if override:
                merged[name] = int(override.group(1))
        timings[tfvars.name] = merged
    return timings


class ClaimLeaseTests(unittest.TestCase):
    def test_worker_lambda_uses_the_shared_timeout_variable(self):
        lambda_tf = (INFRA_DIR / "lambda.tf").read_text()
        worker = re.search(
            r'resource "aws_lambda_function" "webhook_worker" \{(.*?)\n\}', lambda_tf, re.S
        )
        self.assertIn("timeout       = var.lambda_timeout_seconds", worker.group(1))

    def test_claim_lease_is_longer_than_the_worker_timeout(self):
        # A stale claim is taken over once it is CLAIM_LEASE_SECONDS old. That is
        # safe only because the Lambda that holds it is dead by then. Raising the
        # worker timeout to the lease or beyond would let a retry take over a live run.
        for source, timing in _configured_timings().items():
            with self.subTest(source=source):
                self.assertGreater(CLAIM_LEASE_SECONDS, timing["lambda_timeout_seconds"])

    def test_an_sqs_retry_lands_after_the_lease_expires(self):
        # SQS redelivers a failed job every visibility timeout and gives up after
        # maxReceiveCount receives, so the last retry comes at about
        # (maxReceiveCount - 1) x visibility. If the lease outlasts that, every retry
        # sees a fresh claim and the killed run's order goes to the DLQ: only a
        # manual replay would recover it.
        for source, timing in _configured_timings().items():
            with self.subTest(source=source):
                last_retry_seconds = (
                    timing["webhook_queue_max_receive_count"] - 1
                ) * timing["webhook_queue_visibility_timeout_seconds"]
                self.assertLess(CLAIM_LEASE_SECONDS, last_retry_seconds)


if __name__ == "__main__":
    unittest.main()
