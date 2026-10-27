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
