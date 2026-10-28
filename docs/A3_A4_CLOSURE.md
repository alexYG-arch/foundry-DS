# A3/A4 Closure Boundary

Date: 2026-10-28.

## A3-read v2

`ControlViewV2` is an additive, revision-preserving view. `_current` remains the
full dispatch/CAS boundary; it is not replaced. The view is for monitoring,
cancellation and budget/attempt surfaces that do not need source/proposal bodies.

## A3-write

Source dedup is an explicit format. Within the same `proposal_event_id`, an
unchanged root/manifest/snapshot may reuse the existing source capture; cross-goal
reuse is not implied.

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

## A4

Current-view helpers, identity diff, pagination, history hydration and the
bounded renderer are delivered as optional support. They are not acceptance or
a business report by themselves.
