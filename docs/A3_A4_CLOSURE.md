# A3/A4 Closure Boundary

Date: 2026-10-28 (revised after the a3-read-v2 review).

## A3-read v2

`ControlViewV2` (`control_view.build_control_view`, `BuildController.control_view`,
`read-build --control-view --prepared-event-id ID`) is an additive, read-only
projection of authorization, attempt and budget facts. `_current` remains the
full dispatch/CAS boundary; the view carries `dispatch_authority: false`.

What the view guarantees:

- **Revision consistency.** `stream_revision` is read first and every typed read
  is pinned to `stream_revision <= that value`; a writer landing between the
  reads is excluded from both the facts and the revision
  (`read_consistency: PINNED_TO_STREAM_REVISION`). Its `stream_revision` is the
  intended `expected_revision` for a revocation/cancellation decided on these facts.
- **Dispatch vocabulary.** `state` uses `control_view.authority_state`, the same
  function `read-build` uses, and applies `validate_authority_chain` exactly as
  `_current` does: a derived authorization whose source approval was revoked or
  expired reads REVOKED/EXPIRED, an approval without a human reference reads
  APPROVAL_REQUIRED, with `authority_unavailable_reason` naming the code.
- **No bodies.** Source and proposal payloads are never loaded
  (`source_loaded`/`proposal_loaded` are `false`). Plan 1.3 preparations without
  `source_event_id`/`proposal_event_id` are readable.

What it does not do: it is not acceptance, it does not validate source bytes,
verifier bytes or review documents, and it does not replace `_current`.
`control_snapshot` (v1) is now the same projection.

## A3-write

Source dedup is an explicit format (`REVISION_V1_DEDUP`). Within the same
`proposal_event_id`, an unchanged root/manifest/snapshot may reuse the existing
source capture; cross-goal reuse is not implied. Content for one `append_batch`
travels with that call between the store hooks; concurrent appends on one store
object cannot leave a committed event with a dangling content reference.

## A3-migration

Closure scope is the offline tool only:

- read-only source;
- absent target;
- SQLite backup;
- `.commands/.verifiers` copy;
- event projection verification;
- VACUUM of the target.

**The active 8.5 GB database migration/cutover is explicitly removed from the
closure condition by the user on 2026-10-28.** No active database was modified.
The tool's memory profile is a separate engineering item (see the review
report's WP3); until it is streaming, migrating a store of that size is not
within the verified range.

## A4

Current-view helpers, identity diff, pagination, history hydration and the
bounded renderer are delivered as optional support. They are not acceptance or
a business report by themselves.
