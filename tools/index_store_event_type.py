#!/usr/bin/env python3
"""Add the typed-read index to an existing REVISION_V1 / REVISION_V1_DEDUP store.

Offline, explicit, idempotent. The store never creates indexes when it opens
(no automatic migration); this tool is the same kind of operator step as the
dedup migration. It touches no event, trigger or table definition, so the
exact-schema guard still accepts the database afterwards.

    python3 tools/index_store_event_type.py /path/to/control.sqlite3

Stop writers first: index creation on a very large store holds the write lock
while it builds.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

INDEX_NAME = "control_events_program_type_revision"
INDEX_SQL = (f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
             "ON control_events(program_id, event_type, stream_revision)")


def add_index(database_path, *, analyze=True):
    path = Path(database_path).resolve()
    if not path.is_file():
        return {"status": "FAIL", "error": f"control store does not exist: {path}"}
    connection = sqlite3.connect(str(path), timeout=30.0)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "control_events" not in tables:
            return {"status": "FAIL", "error": "not a control event store (control_events table missing)"}
        existing = connection.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
                                      (INDEX_NAME,)).fetchone() is not None
        connection.execute(INDEX_SQL)
        if analyze:
            connection.execute("ANALYZE control_events")
        connection.commit()
        rows = connection.execute("SELECT COUNT(*) FROM control_events").fetchone()[0]
    finally:
        connection.close()
    return {"status": "INDEXED", "database": str(path), "index": INDEX_NAME, "created": not existing,
            "events": rows, "schema_changed": False, "events_changed": False,
            "note": "typed reads (list_events_by_types, control view) now use this index; "
                    "stream reads with elided bodies are unchanged"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("database")
    parser.add_argument("--no-analyze", action="store_true", help="skip ANALYZE after creating the index")
    args = parser.parse_args(argv)
    try:
        result = add_index(args.database, analyze=not args.no_analyze)
    except Exception as exc:
        result = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "INDEXED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
