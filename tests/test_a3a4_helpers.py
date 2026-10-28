"""A3 source reuse and A4 impact/pagination/hydration helpers."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from harness_foundry_factory.build_runtime import reusable_source_event
from harness_foundry_factory.revision_store import RevisionControlEventStore
from harness_foundry_factory.rsi_handoff import HandoffError, build_current_view, hydrate_history, impact_map, paginate

SHA = hashlib.sha256(b"x").hexdigest()


class A3ReuseTests(unittest.TestCase):
    def test_identical_source_capture_is_reusable(self):
        with tempfile.TemporaryDirectory() as d:
            store = RevisionControlEventStore(Path(d) / "control.sqlite3")
            snapshot = {"schema_version": "1.0", "sources": [{"source_id": "S", "text": "x"}]}
            event = store.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED", "payload": {
                "source_root": "/root", "manifest": [{"source_id": "S", "path": "a.md"}],
                "snapshot": snapshot}}], expected_revision=0, idempotency_key="k",
                created_at="2026-10-27T00:00:00Z")[0]
            self.assertEqual(reusable_source_event(store, "P", "/root", [{"source_id": "S", "path": "a.md"}], snapshot)["event_id"], event["event_id"])
            self.assertIsNone(reusable_source_event(store, "P", "/root", [], snapshot))

    def test_hashed_captures_are_found_by_digest_and_legacy_captures_by_comparison(self):
        from unittest.mock import patch
        from harness_foundry_factory.build_runtime import snapshot_digest
        with tempfile.TemporaryDirectory() as d:
            store = RevisionControlEventStore(Path(d) / "control.sqlite3")
            manifest = [{"source_id": "S", "path": "a.md"}]
            legacy_snapshot = {"schema_version": "1.0", "sources": [{"source_id": "S", "text": "legacy"}]}
            hashed_snapshot = {"schema_version": "1.0", "sources": [{"source_id": "S", "text": "hashed"}]}
            legacy = store.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED", "payload": {
                "source_root": "/root", "manifest": manifest, "snapshot": legacy_snapshot}}],
                expected_revision=0, idempotency_key="legacy", created_at="2026-10-27T00:00:00Z")[0]
            hashed = store.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED", "payload": {
                "source_root": "/root", "manifest": manifest, "snapshot": hashed_snapshot,
                "snapshot_sha256": snapshot_digest(hashed_snapshot)}}],
                expected_revision=1, idempotency_key="hashed", created_at="2026-10-27T00:00:00Z")[0]
            self.assertEqual(reusable_source_event(store, "P", "/root", manifest, hashed_snapshot)["event_id"], hashed["event_id"])
            self.assertEqual(reusable_source_event(store, "P", "/root", manifest, legacy_snapshot)["event_id"], legacy["event_id"])
            # A digest match alone never wins: identity fields are still compared.
            self.assertIsNone(reusable_source_event(store, "P", "/elsewhere", manifest, hashed_snapshot))
            # The digest lookup happens inside the store; the full typed read is not used.
            with patch.object(RevisionControlEventStore, "list_events_by_types", side_effect=AssertionError("full read")):
                self.assertEqual(reusable_source_event(store, "P", "/root", manifest, hashed_snapshot)["event_id"], hashed["event_id"])


class A4HelperTests(unittest.TestCase):
    def view(self):
        return build_current_view(baseline={"id": "B", "sha256": SHA},
            changes=[{"id": "C1"}], affected_assertions=[{"id": "A1", "change_ids": ["C1"], "status": "PENDING"}],
            evidence=[], history_refs=[{"id": "H", "sha256": SHA}], pending=["A1"])

    def test_impact_pagination_and_history(self):
        view = self.view()
        self.assertEqual(impact_map(view["changes"], view["affected_assertions"]),
                         [{"change_id": "C1", "assertion_id": "A1", "status": "PENDING"}])
        page = paginate(view, "pending", 0, 1)
        self.assertEqual((page["total"], len(page["items"]), page["has_more"]), (1, 1, False))
        self.assertTrue(hydrate_history(view, lambda ref: "old")[0]["loaded"])
        with self.assertRaises(HandoffError):
            paginate(view, "unknown")


if __name__ == "__main__":
    unittest.main()
