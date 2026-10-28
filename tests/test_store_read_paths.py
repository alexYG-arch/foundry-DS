"""Hot control-plane paths read the stream without deserializing source bodies.

The controller still works on the complete ordered stream (revision arithmetic,
projections, command scans are unchanged); only the one capture a decision
needs is read by event ID. These tests pin that with a differential check
against the full stream and a trace of what SQLite handed to Python.
"""

from contextlib import contextmanager
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_foundry_factory.build_runtime import SOURCE_BODY_ELISION, control_events, source_payload
from harness_foundry_factory.revision_store import RevisionControlEventStore
from harness_foundry_factory.revision_store_dedup import DedupRevisionControlEventStore
from harness_foundry_factory.build_types import RequestValidationError
import test_build_runtime as support


@contextmanager
def row_trace():
    """Record, per deserialized row, whether a source body reached Python."""
    seen = []
    original = RevisionControlEventStore._row_event

    def traced(self, row):
        payload_json = row["payload_json"]
        seen.append((str(row["event_type"]), isinstance(payload_json, str) and '"snapshot":' in payload_json))
        return original(self, row)

    with patch.object(RevisionControlEventStore, "_row_event", traced):
        yield seen


class StoreReadPathTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.source_text = self.f.source_text + ("Large requirement detail.\n" * 20000)
        (self.f.source / "brief.md").write_text(self.f.source_text)
        self.f.review = support.reviewed_document(self.f.source, path=self.f.source / "brief.md")
        self.f.scope["expires_at"] = "2099-01-01T00:00:00Z"   # read-only CLI reads use the real clock
        self.f.prepare()

    def test_elided_stream_is_the_full_stream_minus_source_bodies(self):
        full = self.f.store.list_events(self.f.program)
        elided = control_events(self.f.store, self.f.program)
        self.assertEqual([(e["event_id"], e["stream_revision"], e["event_type"]) for e in full],
                         [(e["event_id"], e["stream_revision"], e["event_type"]) for e in elided])
        for before, after in zip(full, elided):
            if before["event_type"] in SOURCE_BODY_ELISION:
                self.assertEqual(after["payload"]["elided_fields"], ["snapshot"])
                self.assertEqual({k: v for k, v in before["payload"].items() if k != "snapshot"},
                                 {k: v for k, v in after["payload"].items() if k != "elided_fields"})
                self.assertNotIn("snapshot", after["payload"])
            else:
                self.assertEqual(before["payload"], after["payload"])
        body = source_payload(self.f.store, self.f.program, self.f.source_id)
        self.assertEqual(body, full[1]["payload"])
        self.assertIn("Large requirement detail.", body["snapshot"]["sources"][0]["text"])

    def test_current_and_advance_read_source_bodies_only_by_event_id(self):
        controller = self.f.controller()
        with row_trace() as seen:
            events, prepared, plan = controller._current(self.f.prepared_id)
        source_rows = [with_body for kind, with_body in seen if kind == "BUILD_SOURCES_CAPTURED"]
        self.assertTrue(source_rows, "the source capture must still be part of the stream")
        self.assertEqual(source_rows.count(True), 1, "exactly one point read carries the body")
        self.assertEqual(len(events), self.f.store.event_count(self.f.program))
        self.assertEqual(prepared["prepared_event_id"], self.f.prepared_id)
        with row_trace() as seen:
            result = controller.advance(self.f.prepared_id)
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        stream_reads = sum(1 for kind, with_body in seen if kind == "BUILD_SOURCES_CAPTURED" and not with_body)
        body_reads = sum(1 for kind, with_body in seen if kind == "BUILD_SOURCES_CAPTURED" and with_body)
        self.assertGreater(stream_reads, 0)
        self.assertLess(body_reads, stream_reads, "stream reads must dominate; bodies are point reads")

    def test_readback_and_control_view_do_not_parse_source_bodies_in_the_stream(self):
        from harness_foundry_factory.build_entrypoint import read_build, read_build_control_view
        with row_trace() as seen:
            readback = read_build(self.f.store.database_path, self.f.program)
        self.assertEqual(len(readback["sources"]), 1)
        self.assertNotIn("text", readback["sources"][0]["sources"][0])
        kinds = [(kind, body) for kind, body in seen if kind == "BUILD_SOURCES_CAPTURED"]
        self.assertIn(("BUILD_SOURCES_CAPTURED", False), kinds)
        self.assertLessEqual(kinds.count(("BUILD_SOURCES_CAPTURED", True)), 2)  # summary + scope readback
        with row_trace() as seen:
            view = read_build_control_view(self.f.store.database_path, self.f.program, self.f.prepared_id)
        self.assertEqual(view["state"], "APPROVED")
        self.assertFalse(any(kind == "BUILD_SOURCES_CAPTURED" for kind, _ in seen))

    def test_elision_is_validated_and_works_on_the_dedup_store(self):
        with self.assertRaises(RequestValidationError):
            self.f.store.list_events(self.f.program, elide={"BUILD_SOURCES_CAPTURED": ("bad field",)})
        with self.assertRaises(RequestValidationError):
            self.f.store.list_events(self.f.program, elide={"": ("snapshot",)})
        with tempfile.TemporaryDirectory() as d:
            store = DedupRevisionControlEventStore(Path(d) / "dedup.sqlite3")
            snapshot = {"schema_version": "1.0", "sources": [{"source_id": "S", "text": "x" * 1000}]}
            store.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED",
                                      "payload": {"source_root": "/r", "manifest": [], "snapshot": snapshot}}],
                               expected_revision=0, idempotency_key="k", created_at="2026-10-27T00:00:00Z")
            [event] = store.list_events("P", elide=SOURCE_BODY_ELISION)
            self.assertEqual(set(event["payload"]), {"source_root", "manifest", "elided_fields"})
            self.assertEqual(store.get_event("P", event["event_id"])["payload"]["snapshot"], snapshot)


class OfflineIndexToolTests(unittest.TestCase):
    def test_tool_adds_the_typed_read_index_without_touching_events(self):
        import subprocess, sys
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "control.sqlite3"
            store = RevisionControlEventStore(path)
            for index in range(60):
                kind = "BUILD_COMMAND_OBSERVED" if index % 20 else "BUILD_ATTEMPT_STARTED"
                store.append_batch("P", [{"event_type": kind, "payload": {"n": index}}],
                                   expected_revision=index, idempotency_key=f"k{index}", created_at="2026-10-27T00:00:00Z")
            before = store.list_events("P")
            run = subprocess.run([sys.executable, "-B", str(root / "tools/index_store_event_type.py"), str(path)],
                                 capture_output=True, text=True, check=False)
            result = json.loads(run.stdout)
            self.assertEqual((run.returncode, result["status"]), (0, "INDEXED"), run.stderr)
            self.assertEqual(result["index"], "control_events_program_type_revision")
            self.assertTrue(result["created"])
            import sqlite3
            with sqlite3.connect(path) as connection:
                plan = connection.execute(
                    "EXPLAIN QUERY PLAN SELECT * FROM control_events WHERE program_id = ? AND event_type IN (?) "
                    "ORDER BY stream_revision", ("P", "BUILD_ATTEMPT_STARTED")).fetchall()
            self.assertTrue(any("control_events_program_type_revision" in str(row) for row in plan), plan)
            # Store still opens with its exact-schema guard, events are untouched, and the tool is idempotent.
            reopened = RevisionControlEventStore(path)
            self.assertEqual(reopened.list_events("P"), before)
            again = json.loads(subprocess.run([sys.executable, "-B", str(root / "tools/index_store_event_type.py"), str(path)],
                                              capture_output=True, text=True, check=False).stdout)
            self.assertFalse(again["created"])
            missing = subprocess.run([sys.executable, "-B", str(root / "tools/index_store_event_type.py"), str(Path(d) / "nope.sqlite3")],
                                     capture_output=True, text=True, check=False)
            self.assertEqual(missing.returncode, 1)


if __name__ == "__main__":
    unittest.main()
