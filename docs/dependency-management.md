# Dependency Management

How and why this project pins its Python dependencies, and how to bump them
safely.

## Decision

Direct dependencies in [`requirements.txt`](../requirements.txt) are pinned to
**exact versions** — the versions the test suite passes against. Upgrading is a
deliberate, reviewed, tested action, not something that happens silently on the
next `pip install`.

## Why this is locked in

Before pinning, `requirements.txt` listed bare package names with no version
constraints:

```
boto3
fastapi
python-dotenv
squareup
uvicorn
```

That means a `pip install` today and one in six months could resolve to
different **major** versions. The acute risk is `squareup` — the Square SDK:

- This service's correctness depends on Square's Orders, Inventory, Catalog,
  and OAuth APIs behaving as the code expects.
- A major SDK bump can change method signatures or response shapes.
- With unpinned deps, CI and the Lambda deploy would pull the new version with
  no signal, and the failure could surface as **mis-written or unwritten
  inventory** rather than an obvious crash.

For a system that writes to a real merchant's books, reproducibility of the
exact tested dependency set matters more than getting automatic updates.

## What is pinned

The five direct dependencies, pinned to the versions validated by the test
suite (Python 3.14):

| Package | Pinned version | Role |
|---|---|---|
| `squareup` | 44.0.1.20260122 | Square SDK — Orders / Inventory / Catalog / OAuth |
| `boto3` | 1.42.79 | AWS SDK — DynamoDB, SQS, Secrets Manager, SNS |
| `fastapi` | 0.135.1 | Local webhook server framework |
| `uvicorn` | 0.42.0 | ASGI server for local FastAPI |
| `python-dotenv` | 1.2.2 | `.env` loading |

## How to bump a dependency safely

1. Bump the version in `requirements.txt`.
2. Reinstall into the venv: `./.venv/bin/pip install -r requirements.txt`.
3. Run the full suite: `./scripts/sanity_check.sh` — must stay green.
4. For a Square SDK bump specifically, also run a live sandbox canary
   (`./.venv/bin/python -m testing.run_live_cloud_canary tgy_tea_100_sugar`)
   to confirm the real API calls still behave, since unit tests mock the SDK.
5. Commit the bump on its own branch so the dependency change is reviewable in
   isolation.

The point of pinning is that this is the *only* way the dependency set changes —
deliberately, with the tests as the gate.

## Known limitation

This pins **direct** dependencies only. Transitive dependencies (e.g. what
`boto3` or `squareup` themselves depend on) still float at install time. For the
stated risk — a silent major bump of a package this code calls directly — exact
pins on the direct set are the proportionate fix.

If full reproducibility (including transitive deps, ideally with hashes) becomes
necessary, the next step is a lock file via `pip-tools` (`pip-compile` →
`requirements.lock`) or a move to `poetry`/`uv`. That is a larger tooling change
and is intentionally **not** done here; it can be revisited if transitive drift
ever causes a problem.

## How this interacts with deployment

The Lambda deploy workflow builds packages from `requirements.txt`
(`pip install --requirement requirements.txt ... --target ...`). Pinning
therefore locks the deployed Lambda runtime to the same versions the tests pass
against — so what CI validates is what runs in AWS.
