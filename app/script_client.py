"""CLI helper for scripts that need a Square SDK client.

Scripts can be invoked in either mode:

  # OAuth merchant path (uses stored merchant token from DynamoDB + Secrets Manager):
  python -m scripts.NAME --merchant <merchant_id> [--environment sandbox|production] [other args]

  # PAT path (env-based, original behavior):
  python -m scripts.NAME [other args]

The helper parses --merchant and --environment out of argv, returning the
appropriate Square client plus the remaining argv (so each script's existing
flag checks like ``"--apply" in argv`` keep working unchanged).
"""

from app.client import create_square_client, create_square_client_for_merchant
from app.config import get_square_environment_name


def create_square_client_from_args(argv):
    """Build a Square client from CLI args.

    Strips ``--merchant`` and ``--environment`` from ``argv`` in place. If
    ``--merchant`` is given, returns an OAuth-token-backed client (looked up
    via DynamoDB + Secrets Manager). Otherwise falls back to the env-based
    PAT path the scripts have historically used.

    Returns (client, remaining_argv) so callers can keep doing their own
    ``"--apply" in argv``-style checks against the remainder.
    """
    remaining = list(argv)
    merchant_id = _pop_flag(remaining, "--merchant")
    environment = _pop_flag(remaining, "--environment")

    if merchant_id:
        resolved_env = environment or get_square_environment_name()
        return create_square_client_for_merchant(resolved_env, merchant_id), remaining
    return create_square_client(environment_name=environment), remaining


def _pop_flag(argv, flag):
    if flag not in argv:
        return None
    idx = argv.index(flag)
    if idx + 1 >= len(argv):
        raise ValueError(f"{flag} requires a value")
    value = argv[idx + 1]
    del argv[idx : idx + 2]
    return value
