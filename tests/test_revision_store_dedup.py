"""Explicit dedup store: source text stored once, API hydrates the original text."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from harness_foundry_factory.revision_store import RevisionControlEventStore
from harness_foundry_factory.revision_store_dedup import DedupRevisionControlEventStore, migrate_to_dedup

TEXT = "alpha\nbeta\n"


def snapshot():
    return {"schema_version": "1.0", "sources": [{"source_id": "S", "path_or_uri": "a.md",
            "loaded_completely": True, "format": "MARKDOWN", "text": TEXT, "line_count": 2}],
            "semantic_completeness_verified": False, "instructions_executed": False}


class DedupStoreTests(unittest.TestCase):
    def test_text_is_stored_once_and_hydrated_on_read(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "control.sqlite3"
            store = DedupRevisionControlEventStore(path)
            for index in (1, 2):
                store.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED", "payload": {"snapshot": snapshot()}}],
                    expected_revision=index - 1, idempotency_key=f"k{index}", created_at="2026-10-27T00:00:00Z")
            with sqlite3.connect(path) as connection:
                raw = [row[0] for row in connection.execute("SELECT payload_json FROM control_events")]
                content = connection.execute("SELECT text, byte_length FROM control_source_content").fetchall()
            self.assertEqual(len(content), 1)
            self.assertEqual(content[0][0], TEXT)
            self.assertTrue(all(TEXT not in value for value in raw))
            events = store.list_events("P")
            self.assertEqual([row["payload"]["snapshot"]["sources"][0]["text"] for row in events], [TEXT, TEXT])
            replayed = store.idempotent_events("P", "k1")
            self.assertEqual(replayed[0]["payload"]["snapshot"]["sources"][0]["text"], TEXT)

    def test_offline_migration_preserves_events_and_compacts_copy(self):
        from harness_foundry_factory.revision_store import RevisionControlEventStore
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source.sqlite3"; target = Path(d) / "target.sqlite3"
            old = RevisionControlEventStore(source)
            old.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED", "payload": {"snapshot": snapshot()}}],
                expected_revision=0, idempotency_key="k", created_at="2026-10-27T00:00:00Z")
            before = source.read_bytes()
            result = migrate_to_dedup(source, target)
            self.assertEqual(result["status"], "MIGRATED")
            self.assertEqual(source.read_bytes(), before)
            new = DedupRevisionControlEventStore(target, read_only=True)
            self.assertEqual(new.list_events("P")[0]["payload"]["snapshot"]["sources"][0]["text"], TEXT)
            self.assertEqual(new.idempotent_events("P", "k")[0]["payload"]["snapshot"]["sources"][0]["text"], TEXT)

    def test_migration_streams_in_batches_and_verifies_idempotency_replays(self):
        from harness_foundry_factory.revision_store import RevisionControlEventStore
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source.sqlite3"; target = Path(d) / "target.sqlite3"
            old = RevisionControlEventStore(source)
            for index in range(7):
                text = f"body-{index % 3}\n"   # three distinct texts across seven captures
                snap = snapshot(); snap["sources"][0]["text"] = text
                old.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED", "payload": {"snapshot": snap}}],
                    expected_revision=index, idempotency_key=f"k{index}", created_at="2026-10-27T00:00:00Z")
            old.append_batch("Q", [{"event_type": "X", "payload": {"n": 1}}],
                expected_revision=0, idempotency_key="q", created_at="2026-10-27T00:00:00Z")
            result = migrate_to_dedup(source, target, batch_size=2)
            self.assertEqual(result["status"], "MIGRATED")
            self.assertEqual(result["contents"], 3)
            self.assertEqual(result["verification"]["events"], 8)
            self.assertEqual(result["verification"]["idempotency_replays"], 8)
            self.assertTrue(result["verification"]["streaming"])
            new = DedupRevisionControlEventStore(target, read_only=True)
            self.assertEqual([row["payload"]["snapshot"]["sources"][0]["text"] for row in new.iter_events("P", batch_size=3)],
                             [f"body-{index % 3}\n" for index in range(7)])
            self.assertEqual(new.idempotent_events("P", "k4")[0]["payload"]["snapshot"]["sources"][0]["text"], "body-1\n")
            with sqlite3.connect(target) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM control_source_content").fetchone()[0], 3)

    def test_migration_verification_detects_a_divergent_idempotency_replay(self):
        from harness_foundry_factory.revision_store import RevisionControlEventStore
        from harness_foundry_factory.revision_store_dedup import verify_migration
        from harness_foundry_factory.build_types import RequestValidationError
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source.sqlite3"; target = Path(d) / "target.sqlite3"
            old = RevisionControlEventStore(source)
            old.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED", "payload": {"snapshot": snapshot()}}],
                expected_revision=0, idempotency_key="k", created_at="2026-10-27T00:00:00Z")
            migrate_to_dedup(source, target)
            with sqlite3.connect(target) as connection:
                connection.execute("UPDATE control_idempotency SET events_json = '[]' WHERE idempotency_key = 'k'")
            with self.assertRaisesRegex(RequestValidationError, "idempotency replay differs"):
                verify_migration(source, target)

    def test_migration_can_copy_external_observation_dirs(self):
        from harness_foundry_factory.revision_store import RevisionControlEventStore
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source.sqlite3"; target = Path(d) / "target.sqlite3"
            RevisionControlEventStore(source)
            commands = source.with_suffix(".commands"); commands.mkdir(); (commands / "x.json").write_text("{}")
            result = migrate_to_dedup(source, target, copy_external=True)
            self.assertTrue((target.with_suffix(".commands") / "x.json").is_file())
            self.assertEqual(result["external"][".commands"]["target"], str(target.with_suffix(".commands").resolve()))

    def test_v1_store_rejects_dedup_database(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "control.sqlite3"
            DedupRevisionControlEventStore(path)
            with self.assertRaises(Exception):
                RevisionControlEventStore(path)

    def test_interleaved_appends_on_one_instance_never_commit_dangling_content(self):
        """Two writers share one store object; the loser's prepared content must not
        be the only content the winner's committed event can reach."""
        import threading
        from unittest.mock import patch
        from harness_foundry_factory.build_types import RevisionConflictError

        barrier = threading.Barrier(2)
        original = DedupRevisionControlEventStore._prepare_entries

        def interleaved(self, entries):
            name = entries[0]["payload"]["snapshot"]["sources"][0]["source_id"]
            if name == "A":
                result = original(self, entries)
                barrier.wait(timeout=5)       # B prepares after A, before A's transaction
                threading.Event().wait(0.1)
                return result
            barrier.wait(timeout=5)
            result = original(self, entries)
            threading.Event().wait(0.5)       # B enters its transaction after A committed
            return result

        def source(name, text):
            return {"snapshot": {"sources": [{"source_id": name, "text": text}]}}

        with tempfile.TemporaryDirectory() as d:
            store = DedupRevisionControlEventStore(Path(d) / "control.sqlite3")
            outcomes = {}

            def writer(name):
                try:
                    store.append_batch("P", [{"event_type": "BUILD_SOURCES_CAPTURED", "payload": source(name, f"text-{name}")}],
                                       expected_revision=0, idempotency_key=name, created_at="2026-10-27T00:00:00Z")
                    outcomes[name] = "COMMITTED"
                except RevisionConflictError:
                    outcomes[name] = "CONFLICT"

            with patch.object(DedupRevisionControlEventStore, "_prepare_entries", interleaved):
                threads = [threading.Thread(target=writer, args=(name,)) for name in ("A", "B")]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
            self.assertEqual(sorted(outcomes.values()), ["COMMITTED", "CONFLICT"])
            events = store.list_events("P")   # hydration must succeed for every committed event
            self.assertEqual(len(events), 1)
            winner = events[0]["payload"]["snapshot"]["sources"][0]
            self.assertEqual(winner["text"], f"text-{winner['source_id']}")

    def test_v1_store_is_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "control.sqlite3"
            store = DedupRevisionControlEventStore(path)
            store.append_batch("P", [{"event_type": "X", "payload": {"text": TEXT}}],
                expected_revision=0, idempotency_key="k", created_at="2026-10-27T00:00:00Z")
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM control_source_content").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
