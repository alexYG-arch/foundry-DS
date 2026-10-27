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

    def test_v1_store_rejects_dedup_database(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "control.sqlite3"
            DedupRevisionControlEventStore(path)
            with self.assertRaises(Exception):
                RevisionControlEventStore(path)

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
