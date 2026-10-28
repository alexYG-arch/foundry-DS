"""A3-read v2: control facts without source/proposal bodies, consistent with dispatch."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness_foundry_factory.build_correction import POLICY
from harness_foundry_factory.build_entrypoint import read_build_control_view
from harness_foundry_factory.build_types import RequestValidationError
from harness_foundry_factory.control_view import ATTEMPT_TYPES, STATES, build_control_view
from harness_foundry_factory.revision_store import RevisionControlEventStore

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
SCOPE = {"expires_at": "2099-01-01T00:00:00Z", "max_attempts": 3, "max_task_attempts": 2}


class Stream:
    """Append helper that tracks the revision so tests read like event logs."""

    def __init__(self, store, program="P"):
        self.store, self.program, self.revision = store, program, 0

    def append(self, kind, payload, key=None, created_at="2026-10-27T00:00:00Z"):
        event = self.store.append_batch(self.program, [{"event_type": kind, "payload": payload}],
                                        expected_revision=self.revision,
                                        idempotency_key=key or f"k{self.revision}", created_at=created_at)[0]
        self.revision += 1
        return event

    def prepared(self, scope=SCOPE, **extra):
        return self.append("BUILD_AUTHORIZATION_PREPARED",
                           {"scope": scope, "source_event_id": "S", "proposal_event_id": "R", **extra})

    def approved(self, prepared_id, **extra):
        return self.append("BUILD_AUTHORIZATION_APPROVED",
                           {"prepared_event_id": prepared_id, "human_message_ref": "human", **extra})


class ControlViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "control.sqlite3"
        self.store = RevisionControlEventStore(self.path)
        self.stream = Stream(self.store)

    def view(self, prepared_id, now=NOW):
        return build_control_view(self.store, "P", prepared_id, now=now)

    def test_view_reports_control_state_and_budget_without_loading_source(self):
        prepared = self.stream.prepared()
        self.stream.approved(prepared["event_id"])
        self.stream.append("BUILD_ATTEMPT_STARTED", {"prepared_event_id": prepared["event_id"],
                                                      "attempt_id": "A1", "workpack_id": "W"})
        view = self.view(prepared["event_id"])
        self.assertEqual(view["schema_version"], "CONTROL_VIEW_V2")
        self.assertEqual(view["state"], "APPROVED")
        self.assertEqual(view["stream_revision"], 3)
        self.assertFalse(view["source_loaded"])
        self.assertFalse(view["proposal_loaded"])
        self.assertFalse(view["dispatch_authority"])
        self.assertEqual(view["attempts"]["A1"]["status"], "IN_FLIGHT")
        self.assertEqual(view["budget"]["attempts_consumed"], 1)
        self.assertEqual((view["source_event_id"], view["proposal_event_id"]), ("S", "R"))

    def test_state_matrix_covers_every_vocabulary_entry(self):
        seen = {}
        pending = self.stream.prepared()
        seen["APPROVAL_REQUIRED"] = self.view(pending["event_id"])
        approved = self.stream.prepared()
        self.stream.approved(approved["event_id"])
        seen["APPROVED"] = self.view(approved["event_id"])
        revoked = self.stream.prepared()
        self.stream.approved(revoked["event_id"])
        self.stream.append("BUILD_AUTHORIZATION_REVOKED", {"prepared_event_id": revoked["event_id"]})
        seen["REVOKED"] = self.view(revoked["event_id"])
        expired = self.stream.prepared(scope={**SCOPE, "expires_at": "2026-10-01T00:00:00Z"})
        self.stream.approved(expired["event_id"])
        seen["EXPIRED"] = self.view(expired["event_id"])
        successor = self.stream.prepared(rebind_from=approved["event_id"])
        self.stream.approved(successor["event_id"],
                             rebind={"superseded_prepared_ids": [approved["event_id"]], "accepted": {}})
        seen["SUPERSEDED"] = self.view(approved["event_id"])
        for state, view in seen.items():
            self.assertEqual(view["state"], state, view)
        self.assertEqual(set(seen), set(STATES))
        self.assertEqual(seen["SUPERSEDED"]["superseded_by"], successor["event_id"])
        self.assertTrue(seen["REVOKED"]["approved"] and seen["REVOKED"]["revoked"])
        self.assertTrue(seen["EXPIRED"]["approved"] and not seen["EXPIRED"]["revoked"])

    def test_stream_revision_is_pinned_before_the_facts_are_read(self):
        """A writer landing between the view's reads must not appear in the
        revision while being absent from the facts."""
        prepared = self.stream.prepared()
        self.stream.approved(prepared["event_id"])
        store, stream = self.store, self.stream

        class RacingStore(RevisionControlEventStore):
            raced = False

            def list_events_by_types(self, program_id, event_types, **kwargs):
                if tuple(event_types) == ATTEMPT_TYPES and not RacingStore.raced:
                    RacingStore.raced = True
                    stream.append("BUILD_AUTHORIZATION_REVOKED", {"prepared_event_id": prepared["event_id"]},
                                  key="race-revoke")
                return super().list_events_by_types(program_id, event_types, **kwargs)

        view = build_control_view(RacingStore(self.path), "P", prepared["event_id"], now=NOW)
        self.assertTrue(RacingStore.raced)
        self.assertEqual(view["stream_revision"], 2)      # the race landed at revision 3
        self.assertEqual(view["state"], "APPROVED")        # consistent with revision 2
        self.assertEqual(store.event_count("P"), 3)
        self.assertEqual(self.view(prepared["event_id"])["state"], "REVOKED")

    def test_derived_authority_whose_source_was_revoked_is_not_reported_approved(self):
        p1 = self.stream.prepared()
        a1 = self.stream.approved(p1["event_id"])
        p2 = self.stream.prepared(rebind_from=p1["event_id"])
        self.stream.append("BUILD_AUTHORIZATION_APPROVED", {"prepared_event_id": p2["event_id"],
            "derived_authority": {"policy": POLICY, "source_prepared_event_id": p1["event_id"],
                                  "source_approval_event_id": a1["event_id"]}})
        self.assertEqual(self.view(p2["event_id"])["state"], "APPROVED")
        self.stream.append("BUILD_AUTHORIZATION_REVOKED", {"prepared_event_id": p1["event_id"]})
        view = self.view(p2["event_id"])
        self.assertEqual(view["state"], "REVOKED")
        self.assertFalse(view["revoked"], "the derived preparation itself carries no revocation event")
        self.assertEqual(view["authority_unavailable_reason"], "AUTHORIZATION_REVOKED")

    def test_approval_without_a_human_reference_is_not_dispatchable(self):
        prepared = self.stream.prepared()
        self.stream.append("BUILD_AUTHORIZATION_APPROVED", {"prepared_event_id": prepared["event_id"]})
        view = self.view(prepared["event_id"])
        self.assertEqual(view["state"], "APPROVAL_REQUIRED")
        self.assertEqual(view["authority_unavailable_reason"], "AUTHORIZATION_NOT_HUMAN")

    def test_plan_13_preparation_without_source_binding_is_readable(self):
        scope = {"scope_version": "1.3", **SCOPE}
        prepared = self.stream.append("BUILD_AUTHORIZATION_PREPARED",
                                      {"scope": scope, "plan": {"schema_version": "1.3", "workpacks": []}})
        self.stream.approved(prepared["event_id"])
        view = self.view(prepared["event_id"])
        self.assertEqual((view["state"], view["plan_schema_version"]), ("APPROVED", "1.3"))
        self.assertIsNone(view["source_event_id"])
        self.assertIsNone(view["proposal_event_id"])

    def test_missing_preparation_and_bad_timestamps_are_request_errors(self):
        with self.assertRaisesRegex(RequestValidationError, "preparation is missing"):
            self.view("CEVT-NOPE")
        other = self.stream.append("BUILD_PLAN_PROPOSED", {"plan": {}})
        with self.assertRaisesRegex(RequestValidationError, "preparation is missing"):
            self.view(other["event_id"])
        naive = self.stream.prepared(scope={**SCOPE, "expires_at": "2099-01-01T00:00:00"})
        with self.assertRaisesRegex(RequestValidationError, "timezone"):
            self.view(naive["event_id"])
        broken = self.stream.prepared(scope={**SCOPE, "expires_at": "not-a-date"})
        with self.assertRaisesRegex(RequestValidationError, "ISO timestamp"):
            self.view(broken["event_id"])

    def test_control_snapshot_is_the_same_projection(self):
        from harness_foundry_factory.build_runtime import BuildController
        prepared = self.stream.prepared()
        self.stream.approved(prepared["event_id"])
        controller = BuildController(self.store, "P", clock=lambda: NOW)
        self.assertEqual(controller.control_snapshot(prepared["event_id"]), controller.control_view(prepared["event_id"]))

    def test_read_build_control_view_is_read_only_and_cas_ready(self):
        prepared = self.stream.prepared()
        self.stream.approved(prepared["event_id"])
        result = read_build_control_view(self.path, "P", prepared["event_id"])
        self.assertEqual(result["status"], "BUILD_CONTROL_VIEW")
        self.assertEqual(result["stream_revision"], 2)
        self.assertFalse(result["writes_performed"])
        self.assertEqual(self.store.event_count("P"), 2)
        with self.assertRaises(RequestValidationError):
            read_build_control_view(self.path, "P", "")


if __name__ == "__main__":
    unittest.main()
