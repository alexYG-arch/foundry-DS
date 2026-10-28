# A3-写/A3-迁：来源正文去重

## New opt-in store

`DedupRevisionControlEventStore` (`REVISION_V1_DEDUP`) keeps the existing event
API and stores source `text` once in `control_source_content`; event payloads and
idempotency records keep `{"content_sha256": ...}` references. Reads hydrate the
original text; exact request/event identity, revisions and idempotency keys are
preserved.

The content for one `append_batch` travels with that call between the store
hooks (`_prepare_entries` returns it, `_append_aux` receives it). Concurrent
appends on one store object therefore cannot leave a committed event whose
content reference was never written.

This is an explicit format. Existing `REVISION_V1` stores are not changed and
old readers are not promised to read a dedup store.

## Source reuse (`capture-build-sources`)

A new capture records `snapshot_sha256` (SHA-256 of the canonical snapshot).
With `reuse_unchanged` (default), an identical root/manifest/snapshot under the
same proposal reuses the earlier capture: the digest is matched inside SQLite
(`json_extract`) and only same-digest candidates are compared byte for byte;
captures from before the digest existed are compared the old way.

Reuse is still a CAS operation. The request's `expected_revision` must equal the
current stream head, exactly as an append would require; otherwise
`STATE_REVISION_CONFLICT`. The response is
`BUILD_SOURCES_REUSED_NOT_SEMANTICALLY_ACCEPTED` with `reused: true`,
`control_state_write: false`, `reused_event_revision` (the old event) and
`stream_revision` (the current head, i.e. the next `expected_revision`).

## Offline migration

```bash
python3 tools/migrate_store_dedup.py /path/to/source.sqlite3 /path/to/target.sqlite3 [--batch-size 500]
```

The source is opened read-only; the target must be absent. The copy uses the
SQLite backup API (WAL included), preserves event IDs/revisions/order and
idempotency keys, and rewrites rows in bounded batches, inserting content as it
is found: memory is bounded by the batch, not by the store. Verification
streams both sides and compares every event (identity, revision, type,
hydrated payload, time) and every idempotency replay. It does not modify or
shrink the source, and it does not migrate external command/verifier/evidence
files unless `--copy-observations` is given.

## Boundary

Dedup is not compression, not a replacement for VACUUM, and not proof that an
active 8 GB store shrank. Active-database migration still needs a
stopped/consistent copy, evidence attachment checks and rollback; the tool's
streaming behaviour has been exercised on synthetic stores, not on that
database.
