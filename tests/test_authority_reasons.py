"""Stable authority reasons; English message changes must not change classification."""

from datetime import datetime, timezone
import unittest

from harness_foundry_factory.build_correction import validate_authority_chain
from harness_foundry_factory.build_types import AuthorityUnavailableError


def event(event_id, kind, payload, revision):
    return {"event_id": event_id, "event_type": kind, "payload": payload, "stream_revision": revision}


class AuthorityReasonTests(unittest.TestCase):
    def assert_reason(self, events, expected):
        with self.assertRaises(AuthorityUnavailableError) as caught:
            validate_authority_chain(events, "P", datetime(2026, 10, 27, tzinfo=timezone.utc))
        self.assertEqual(caught.exception.reason_code, expected)

    def test_revoked_is_stable(self):
        events = [
            event("P", "BUILD_AUTHORIZATION_PREPARED", {"scope": {"expires_at": "2099-01-01T00:00:00Z"}}, 1),
            event("A", "BUILD_AUTHORIZATION_APPROVED", {"prepared_event_id": "P", "human_message_ref": "x"}, 2),
            event("R", "BUILD_AUTHORIZATION_REVOKED", {"prepared_event_id": "P"}, 3),
        ]
        self.assert_reason(events, "AUTHORIZATION_REVOKED")

    def test_expired_is_stable(self):
        events = [
            event("P", "BUILD_AUTHORIZATION_PREPARED", {"scope": {"expires_at": "2000-01-01T00:00:00Z"}}, 1),
            event("A", "BUILD_AUTHORIZATION_APPROVED", {"prepared_event_id": "P", "human_message_ref": "x"}, 2),
        ]
        self.assert_reason(events, "AUTHORIZATION_EXPIRED")

    def test_absent_is_stable(self):
        events = [event("P", "BUILD_AUTHORIZATION_PREPARED", {"scope": {"expires_at": "2099-01-01T00:00:00Z"}}, 1)]
        self.assert_reason(events, "AUTHORIZATION_ABSENT")


if __name__ == "__main__":
    unittest.main()
