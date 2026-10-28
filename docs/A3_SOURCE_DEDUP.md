# A3-写/A3-迁：来源正文去重

## New opt-in store

`DedupRevisionControlEventStore` (`REVISION_V1_DEDUP`) keeps the existing event
API and stores source `text` once in `control_source_content`; event payloads and
idempotency records keep `{"content_sha256": ...}` references. Reads hydrate the
original text; exact request/event identity, revisions and idempotency keys are
preserved.

This is an explicit format. Existing `REVISION_V1` stores are not changed and
old readers are not promised to read a dedup store.

## Offline migration

```bash
python3 tools/migrate_store_dedup.py /path/to/source.sqlite3 /path/to/target.sqlite3
```

The source is opened read-only; the target must be absent. The copy uses the
SQLite backup API (WAL included), preserves event IDs/revisions/order and
idempotency keys, and verifies content hydration. It does not modify or shrink
the source, and it does not migrate external command/verifier/evidence files.

## Boundary

Dedup is not compression, not a replacement for VACUUM, and not proof that an
active 8 GB store shrank. Active-database migration still needs a stopped/consistent
copy, evidence attachment checks and rollback.
