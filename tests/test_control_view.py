"""A3-read v2: control facts without source/proposal bodies."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness_foundry_factory.control_view import build_control_view
from harness_foundry_factory.revision_store import RevisionControlEventStore


def event(kind, payload, revision):
    return {"event_type": kind, "payload": payload}


class ControlViewTests(unittest.TestCase):
    def test_view_reports_control_state_and_budget_without_loading_source(self):
        with tempfile.TemporaryDirectory() as d:
            store = RevisionControlEventStore(Path(d) / "control.sqlite3")
            scope = {"expires_at": "2099-01-01T00:00:00Z", "max_attempts": 3, "max_task_attempts": 2}
            prepared = store.append_batch("P", [event("BUILD_AUTHORIZATION_PREPARED",
                {"scope": scope, "source_event_id": "S", "proposal_event_id": "R"}, 0)],
                expected_revision=0, idempotency_key="p", created_at="2026-10-27T00:00:00Z")[0]
            store.append_batch("P", [event("BUILD_AUTHORIZATION_APPROVED",
                {"prepared_event_id": prepared["event_id"], "human_message_ref": "x"}, 1)],
                expected_revision=1, idempotency_key="a", created_at="2026-10-27T00:00:00Z")
            store.append_batch("P", [event("BUILD_ATTEMPT_STARTED",
                {"prepared_event_id": prepared["event_id"], "attempt_id": "A1", "workpack_id": "W"}, 2)],
                expected_revision=2, idempotency_key="s", created_at="2026-10-27T00:00:00Z")
            view = build_control_view(store, "P", prepared["event_id"],
                                      now=datetime(2026, 10, 27, tzinfo=timezone.utc))
            self.assertEqual(view["schema_version"], "CONTROL_VIEW_V2")
            self.assertEqual(view["state"], "APPROVED")
            self.assertFalse(view["source_loaded"])
            self.assertFalse(view["proposal_loaded"])
            self.assertEqual(view["attempts"]["A1"]["status"], "IN_FLIGHT")
            self.assertEqual(view["budget"]["attempts_consumed"], 1)


if __name__ == "__main__":
    unittest.main()
