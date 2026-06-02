"""HMAC-signed operator session cookie for the onboarding landing page.

We don't want a server-side session table for a one-merchant tool, so the
session lives entirely in a signed cookie value of the form ``<payload>.<sig>``
where:

* ``payload`` = base64url(JSON({"issued_at": <int>, "expires_at": <int>}))
* ``sig`` = hex(HMAC-SHA256(signing_key, payload))

Verification is constant-time. The cookie carries no secret — only timestamps —
so a leak only enables replay for the remaining lifetime, which we bound with a
short TTL (~2 hours by default). See docs/secrets-and-security.md for the full
threat model.
"""

import base64
import hmac
import json
import time
from hashlib import sha256

from app.config import (
    get_operator_session_signing_key,
    get_operator_session_ttl_seconds,
)


COOKIE_NAME = "mosa_operator_session"


def _b64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value):
    padding = b"=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii") + padding)


def _sign(payload_b64, signing_key):
    return hmac.new(signing_key.encode("utf-8"), payload_b64.encode("ascii"), sha256).hexdigest()


def issue_session_value(*, ttl_seconds=None, signing_key=None, now=None):
    """Build the signed cookie value for a freshly authenticated operator."""
    if signing_key is None:
        signing_key = get_operator_session_signing_key()
    if ttl_seconds is None:
        ttl_seconds = get_operator_session_ttl_seconds()
    if now is None:
        now = int(time.time())

    expires_at = now + ttl_seconds
    payload = {"issued_at": now, "expires_at": expires_at}
    payload_b64 = _b64url_encode(json.dumps(payload, sort_keys=True).encode("utf-8"))
    sig = _sign(payload_b64, signing_key)
    return f"{payload_b64}.{sig}", expires_at


def verify_session_value(value, *, signing_key=None, now=None):
    """Return the decoded payload if valid + unexpired; otherwise None.

    Constant-time on the signature comparison. Any malformed input is treated
    as invalid (returns None) — no exceptions leak to the caller.
    """
    if not value or "." not in value:
        return None

    payload_b64, _, sig = value.partition(".")
    if not payload_b64 or not sig:
        return None

    if signing_key is None:
        try:
            signing_key = get_operator_session_signing_key()
        except ValueError:
            return None

    expected_sig = _sign(payload_b64, signing_key)
    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, int):
        return None

    if now is None:
        now = int(time.time())
    if now >= expires_at:
        return None

    return payload


def set_session_cookie(response, value, *, max_age, secure=True):
    """Set the operator session cookie with safe defaults.

    ``secure=False`` is only used for local non-HTTPS dev. Production should
    always run under HTTPS so the cookie is always sent securely.
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response):
    response.delete_cookie(key=COOKIE_NAME, path="/")
