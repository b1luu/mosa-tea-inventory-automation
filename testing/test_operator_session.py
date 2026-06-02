import unittest

from app.operator_session import issue_session_value, verify_session_value


SIGNING_KEY = "test-signing-key-32-bytes-please-1234567890"
OTHER_KEY = "different-signing-key-not-the-real-one-9876"


class OperatorSessionTests(unittest.TestCase):
    def test_issue_then_verify_roundtrip(self):
        value, expires_at = issue_session_value(
            ttl_seconds=3600, signing_key=SIGNING_KEY, now=1_000_000
        )
        payload = verify_session_value(value, signing_key=SIGNING_KEY, now=1_000_010)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["expires_at"], expires_at)
        self.assertEqual(payload["issued_at"], 1_000_000)

    def test_expired_token_returns_none(self):
        value, _ = issue_session_value(
            ttl_seconds=3600, signing_key=SIGNING_KEY, now=1_000_000
        )
        # Verify at a time well past expiry.
        self.assertIsNone(
            verify_session_value(value, signing_key=SIGNING_KEY, now=1_999_999)
        )

    def test_tampered_payload_fails_signature_check(self):
        value, _ = issue_session_value(
            ttl_seconds=3600, signing_key=SIGNING_KEY, now=1_000_000
        )
        payload_b64, _, sig = value.partition(".")
        # Flip one character in the payload portion.
        mangled = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B")
        tampered = f"{mangled}.{sig}"
        self.assertIsNone(
            verify_session_value(tampered, signing_key=SIGNING_KEY, now=1_000_010)
        )

    def test_wrong_signing_key_rejects_valid_payload(self):
        value, _ = issue_session_value(
            ttl_seconds=3600, signing_key=SIGNING_KEY, now=1_000_000
        )
        self.assertIsNone(
            verify_session_value(value, signing_key=OTHER_KEY, now=1_000_010)
        )

    def test_malformed_values_return_none(self):
        for bad in [None, "", "no-dot-here", "only-dot.", ".only-sig", "a.b.c.d"]:
            self.assertIsNone(
                verify_session_value(bad, signing_key=SIGNING_KEY, now=1_000_000),
                msg=f"expected None for {bad!r}",
            )

    def test_value_format_is_payload_dot_sig(self):
        value, _ = issue_session_value(
            ttl_seconds=60, signing_key=SIGNING_KEY, now=1_000_000
        )
        parts = value.split(".")
        self.assertEqual(len(parts), 2)
        # Signature is 64-hex chars (SHA256).
        self.assertEqual(len(parts[1]), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in parts[1]))


if __name__ == "__main__":
    unittest.main()
