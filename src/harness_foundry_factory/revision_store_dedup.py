"""Opt-in REVISION_V1 store with same-database source-content deduplication.

This is a new explicit format. Existing REVISION_V1 stores and readers remain
untouched; a dedup store stores source text once in control_source_content and
keeps lightweight references in event/idempotency JSON, hydrating on read.
"""

from __future__ import annotations

import copy
from pathlib import Path
import hashlib
import json
from typing import Any, Mapping

from .build_types import RequestValidationError
from .revision_store import RevisionControlEventStore


_CONTENT_TABLE = """
CREATE TABLE IF NOT EXISTS control_source_content (
    content_sha256 TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    byte_length INTEGER NOT NULL
)
"""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()



def migrate_to_dedup(source_path, target_path, *, copy_external=False, batch_size=500):
    """Offline copy V1 -> dedup format; source is opened read-only and untouched.

    Caller must stop writers and choose an absent target. The copy uses the
    SQLite backup API (including WAL) and preserves event IDs, revisions,
    idempotency keys and event order. Rows are rewritten in ``batch_size``
    batches and content is inserted as it is found, so memory stays bounded
    by the batch, not by the store.
    """
    import sqlite3
    from .build_types import canonical_json
    from .revision_store import CONTROL_EVENT_STORE_TRIGGER_SQL

    source = Path(source_path).resolve()
    target = Path(target_path).resolve()
    if not source.is_file() or target.exists():
        raise RequestValidationError("migration requires an existing source and absent target")
    if type(batch_size) is not int or batch_size <= 0:
        raise RequestValidationError("batch_size must be positive")
    source_connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    content_count = 0
    try:
        if source_connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_source_content'").fetchone():
            raise RequestValidationError("source is already a dedup store")
        target_connection = sqlite3.connect(str(target))
        try:
            source_connection.backup(target_connection)
            target_connection.execute(_CONTENT_TABLE)
            for name in CONTROL_EVENT_STORE_TRIGGER_SQL:
                target_connection.execute(f"DROP TRIGGER IF EXISTS {name}")
            target_connection.commit()

            def store_contents(found):
                nonlocal content_count
                for digest, text in found.items():
                    inserted = target_connection.execute(
                        "INSERT OR IGNORE INTO control_source_content(content_sha256, text, byte_length) VALUES (?, ?, ?)",
                        (digest, text, len(text.encode("utf-8")))).rowcount
                    content_count += max(inserted, 0)

            # Events: walk by sequence in bounded batches, committing each batch,
            # so the migration never holds the whole store (or every unique
            # text) in memory.
            last = 0
            while True:
                rows = target_connection.execute(
                    "SELECT sequence, event_id, payload_json FROM control_events WHERE sequence > ? "
                    "ORDER BY sequence LIMIT ?", (last, batch_size)).fetchall()
                if not rows:
                    break
                for sequence, event_id, payload_json in rows:
                    payload, found = DedupRevisionControlEventStore._compact(json.loads(payload_json))
                    store_contents(found)
                    target_connection.execute("UPDATE control_events SET payload_json = ? WHERE event_id = ?",
                                              (canonical_json(payload), event_id))
                    last = sequence
                target_connection.commit()
            last = 0
            while True:
                rows = target_connection.execute(
                    "SELECT rowid, program_id, idempotency_key, request_json, events_json FROM control_idempotency "
                    "WHERE rowid > ? ORDER BY rowid LIMIT ?", (last, batch_size)).fetchall()
                if not rows:
                    break
                for rowid, program_id, key, request_json, events_json in rows:
                    request = json.loads(request_json)
                    compact_entries = []
                    for entry in request["entries"]:
                        payload, found = DedupRevisionControlEventStore._compact(entry["payload"])
                        store_contents(found)
                        compact_entries.append({"event_type": entry["event_type"], "payload": payload})
                    events = []
                    for event in json.loads(events_json):
                        payload, found = DedupRevisionControlEventStore._compact(event["payload"])
                        store_contents(found)
                        events.append({**event, "payload": payload})
                    target_connection.execute(
                        "UPDATE control_idempotency SET request_json = ?, events_json = ? WHERE program_id = ? AND idempotency_key = ?",
                        (canonical_json({"expected_revision": request["expected_revision"], "entries": compact_entries}),
                         canonical_json(events), program_id, key))
                    last = rowid
                target_connection.commit()
            for sql in CONTROL_EVENT_STORE_TRIGGER_SQL.values():
                target_connection.execute(sql)
            target_connection.commit()
            target_connection.execute("VACUUM")
            target_connection.commit()
        finally:
            target_connection.close()
    finally:
        source_connection.close()
    external = {}
    if copy_external:
        import shutil
        for suffix in (".commands", ".verifiers"):
            source_dir = source.with_suffix(suffix)
            target_dir = target.with_suffix(suffix)
            if source_dir.is_dir():
                if target_dir.exists():
                    raise RequestValidationError(f"migration target external dir already exists: {target_dir}")
                shutil.copytree(source_dir, target_dir)
                external[suffix] = {"source": str(source_dir), "target": str(target_dir)}
    verification = verify_migration(source, target, batch_size=batch_size)
    return {"status": "MIGRATED", "source": str(source), "target": str(target),
            "contents": content_count, "external": external, "verification": verification}


def verify_migration(source_path, target_path, *, batch_size=500):
    """Compare source V1 and target dedup by event identity, hydrated payloads
    and idempotency replays, streaming both sides in batches."""
    from .revision_store import RevisionControlEventStore
    source = RevisionControlEventStore(source_path, read_only=True, storage_format="REVISION_V1")
    target = DedupRevisionControlEventStore(target_path, read_only=True)
    # Compare every Program present in source without assuming one Program.
    source_ids = sorted(source.list_program_ids())
    target_ids = sorted(target.list_program_ids())
    if source_ids != target_ids:
        raise RequestValidationError("migration Program set differs")
    events = 0
    replays = 0
    for program in source_ids:
        if source.event_count(program) != target.event_count(program):
            raise RequestValidationError(f"migration event count differs for {program}")
        for old in source.iter_events(program, batch_size=batch_size):
            new = target.get_event(program, old["event_id"])
            if new is None or any(old[key] != new[key] for key in ("stream_revision", "event_type", "payload", "created_at")):
                raise RequestValidationError(f"migration event projection differs for {program}")
            events += 1
        source_keys = source.list_idempotency_keys(program)
        if source_keys != target.list_idempotency_keys(program):
            raise RequestValidationError(f"migration idempotency key set differs for {program}")
        for key in source_keys:
            if source.idempotent_events(program, key) != target.idempotent_events(program, key):
                raise RequestValidationError(f"migration idempotency replay differs for {program}")
            replays += 1
    return {"status": "PASS", "programs": source_ids, "events": events, "idempotency_replays": replays,
            "streaming": True}


class DedupRevisionControlEventStore(RevisionControlEventStore):
    """REVISION_V1 event/API semantics plus explicit source-content references."""

    storage_format = "REVISION_V1_DEDUP"

    def __init__(self, database_path, *, read_only: bool = False):
        super().__init__(database_path, read_only=read_only, storage_format="REVISION_V1", _allow_dedup=True)
        if read_only:
            with self._connection() as connection:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_source_content'"
                ).fetchone()
            if not exists:
                raise RequestValidationError("dedup store lacks control_source_content")
        else:
            with self._connection() as connection:
                connection.execute(_CONTENT_TABLE)
                connection.commit()

    @staticmethod
    def _compact(payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        value = copy.deepcopy(dict(payload))
        contents: dict[str, str] = {}
        snapshot = value.get("snapshot")
        if isinstance(snapshot, Mapping):
            sources = snapshot.get("sources")
            if isinstance(sources, list):
                for source in sources:
                    if isinstance(source, dict) and isinstance(source.get("text"), str):
                        text = source["text"]
                        digest = _digest(text)
                        contents[digest] = text
                        source["text"] = {"content_sha256": digest}
        return value, contents

    def _prepare_entries(self, entries):
        compacted, contents = [], {}
        for entry in entries:
            payload, found = self._compact(entry["payload"])
            compacted.append({"event_type": entry["event_type"], "payload": payload})
            contents.update(found)
        return compacted, contents

    def _append_aux(self, connection, entries, contents):
        # Contents arrive with this call; no instance attribute is shared
        # between concurrent appends on the same store object.
        for digest, text in (contents or {}).items():
            existing = connection.execute(
                "SELECT text FROM control_source_content WHERE content_sha256 = ?", (digest,)
            ).fetchone()
            if existing is not None:
                if existing["text"] != text:
                    raise RequestValidationError("source content digest collision")
            else:
                connection.execute(
                    "INSERT INTO control_source_content(content_sha256, text, byte_length) VALUES (?, ?, ?)",
                    (digest, text, len(text.encode("utf-8"))))

    def _hydrate(self, payload: Any, connection) -> Any:
        value = copy.deepcopy(payload)
        snapshot = value.get("snapshot") if isinstance(value, Mapping) else None
        if isinstance(snapshot, Mapping):
            sources = snapshot.get("sources")
            if isinstance(sources, list):
                for source in sources:
                    if not isinstance(source, dict):
                        continue
                    reference = source.get("text")
                    if isinstance(reference, dict) and set(reference) == {"content_sha256"}:
                        row = connection.execute(
                            "SELECT text FROM control_source_content WHERE content_sha256 = ?",
                            (reference["content_sha256"],)).fetchone()
                        if row is None:
                            raise RequestValidationError("source content reference is missing")
                        source["text"] = str(row["text"])
        return value

    def append_batch(self, program_id, entries, **kwargs):
        appended = super().append_batch(program_id, entries, **kwargs)
        with self._connection() as connection:
            return [{"schema_version": row["schema_version"], "event_id": row["event_id"],
                     "program_id": row["program_id"], "stream_revision": row["stream_revision"],
                     "event_type": row["event_type"],
                     "payload": self._hydrate(row["payload"], connection),
                     "created_at": row["created_at"]} for row in appended]

    def idempotent_events(self, program_id, idempotency_key):
        events = super().idempotent_events(program_id, idempotency_key)
        if events is None:
            return None
        with self._connection() as connection:
            return [{**event, "payload": self._hydrate(event["payload"], connection)} for event in events]

    _idempotent_events = idempotent_events

    def list_events(self, program_id):
        events = super().list_events(program_id)
        with self._connection() as connection:
            return [{**event, "payload": self._hydrate(event["payload"], connection)} for event in events]

    def list_events_by_types(self, program_id, event_types, **kwargs):
        events = super().list_events_by_types(program_id, event_types, **kwargs)
        return self._hydrate_rows(events)

    def list_events_by_payload_field(self, program_id, event_type, field, value, **kwargs):
        events = super().list_events_by_payload_field(program_id, event_type, field, value, **kwargs)
        return self._hydrate_rows(events)

    def _hydrate_rows(self, events):
        with self._connection() as connection:
            return [{**event, "payload": self._hydrate(event["payload"], connection)} for event in events]

    def get_event(self, program_id, event_id):
        event = super().get_event(program_id, event_id)
        if event is None:
            return None
        with self._connection() as connection:
            return {**event, "payload": self._hydrate(event["payload"], connection)}
