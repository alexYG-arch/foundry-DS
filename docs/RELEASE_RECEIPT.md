# Release Receipt V1

`tools/release_receipt.py` binds one release claim to concrete evidence; it does
not turn source diagnostics or a GitHub branch into acceptance by itself.

Required inputs:

- commit and package SHA-256;
- source-gate report (`SOURCE_CHECKS_PASS`);
- single-process full-regression output (`OK`, 0 failures/errors);
- same-package two-case evidence;
- spec lock evidence;
- publication evidence (branch/commit/package digest);
- native Codex acceptance, or an explicit user waiver;
- physical sibling spec status.

Statuses:

- `ACCEPTED`: all required gates PASS and native Codex PASS;
- `ACCEPTED_WITH_LIMITS`: core evidence passes, but explicit limits (for example
  Codex deferral or missing physical sibling spec) remain;
- `REJECTED`: any required evidence mismatch or failure.

`release_accepted=true` is emitted only for `ACCEPTED`. A local release with
limits can be `local_release_accepted=true` while `release_accepted=false`.
