"""A3-read v2: lightweight, revision-consistent control view.

The dispatch boundary `_current` still owns full source/review/byte validation;
this view answers monitoring, cancellation and budget/attempt questions without
loading source or proposal bodies.

Two properties make it usable as a CAS basis:

- Consistency: the stream revision is read *first*, and every typed read is
  pinned to ``stream_revision <= that value``. A writer landing between the
  reads is therefore excluded from both the facts and the revision, instead
  of appearing in the revision only.
- Same vocabulary as dispatch: ``state`` applies the same authority-chain
  check (`validate_authority_chain`) that `_current` applies, so a derived
  authorization whose source approval was revoked reads as REVOKED here too.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .build_correction import validate_authority_chain
from .build_rebind import superseding_prepared
from .build_state import attempt_budget, project_budget_attempts, project_execution_state
from .build_types import RequestValidationError, parse_utc

SCHEMA_VERSION = "CONTROL_VIEW_V2"
AUTH_TYPES = ("BUILD_AUTHORIZATION_PREPARED", "BUILD_AUTHORIZATION_APPROVED", "BUILD_AUTHORIZATION_REVOKED")
ATTEMPT_TYPES = ("BUILD_ATTEMPT_STARTED", "BUILD_ATTEMPT_FINISHED", "BUILD_ATTEMPT_RECOVERED",
                 "BUILD_ATTEMPT_RESOLVED", "BUILD_ACCEPTANCE_INVALIDATED")
STATES = ("SUPERSEDED", "REVOKED", "EXPIRED", "APPROVED", "APPROVAL_REQUIRED")


def authority_state(events, prepared_id: str, prepared: dict, now: datetime) -> dict[str, Any]:
    """The state vocabulary shared by `read-build` and the control view.

    ``events`` must contain at least the authorization families for the whole
    Program (ancestors of a derived authorization live under other prepared
    IDs). Precedence: SUPERSEDED > REVOKED > EXPIRED > APPROVED > APPROVAL_REQUIRED,
    then an authority-chain failure demotes APPROVED exactly as dispatch would
    refuse it.
    """
    approved = any(row["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                   and row["payload"].get("prepared_event_id") == prepared_id for row in events)
    revoked = any(row["event_type"] == "BUILD_AUTHORIZATION_REVOKED"
                  and row["payload"].get("prepared_event_id") == prepared_id for row in events)
    successor = superseding_prepared(events, prepared_id)
    expires = parse_utc(prepared["scope"]["expires_at"])
    state = ("SUPERSEDED" if successor else "REVOKED" if revoked else
             "EXPIRED" if now >= expires else "APPROVED" if approved else "APPROVAL_REQUIRED")
    approval = next((row for row in reversed(events) if row["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                     and row["payload"].get("prepared_event_id") == prepared_id), None)
    authority: dict[str, Any] = {}
    if approval is not None and approval["payload"].get("approval_basis"):
        authority["approval_basis"] = approval["payload"]["approval_basis"]
    if approval is not None and approval["payload"].get("derived_authority"):
        authority["derived_authority"] = approval["payload"]["derived_authority"]
    if state == "APPROVED":
        try:
            validate_authority_chain(events, prepared_id, now)
        except RequestValidationError as exc:
            code = (exc.details or {}).get("reason_code", "AUTHORIZATION_CHAIN_INVALID")
            authority["authority_unavailable_reason"] = code
            authority["authority_unavailable_message"] = str(exc)
            state = ("REVOKED" if code == "AUTHORIZATION_REVOKED" else
                     "EXPIRED" if code == "AUTHORIZATION_EXPIRED" else "APPROVAL_REQUIRED")
    return {"state": state, "approved": approved, "revoked": revoked, "superseded": successor is not None,
            **({"superseded_by": successor} if successor else {}), **authority}


def build_control_view(store, program_id: str, prepared_id: str, *, now=None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    # Pin every read to the revision observed up front: facts and revision
    # then describe the same prefix of the stream.
    revision = store.event_count(program_id)
    prepared_event = store.get_event(program_id, prepared_id)
    if (prepared_event is None or prepared_event["event_type"] != "BUILD_AUTHORIZATION_PREPARED"
            or prepared_event["stream_revision"] > revision):
        raise RequestValidationError("control view preparation is missing")
    prepared = prepared_event["payload"]
    auth = store.list_events_by_types(program_id, AUTH_TYPES, up_to_revision=revision)
    attempt_events = store.list_events_by_types(program_id, ATTEMPT_TYPES, up_to_revision=revision)
    events = sorted(auth + attempt_events, key=lambda row: row["stream_revision"])
    authority = authority_state(events, prepared_id, prepared, current)
    attempts, accepted = project_execution_state(events, prepared_id)
    budget = attempt_budget(prepared["scope"], list(project_budget_attempts(events, prepared_id).values()))
    plan = prepared.get("plan") if isinstance(prepared.get("plan"), dict) else None
    return {"schema_version": SCHEMA_VERSION, "program_id": program_id,
            "prepared_event_id": prepared_id, "stream_revision": revision,
            "read_consistency": "PINNED_TO_STREAM_REVISION",
            **authority, "expires_at": prepared["scope"]["expires_at"],
            # 1.3 preparations recorded outside the host flow may lack these bindings.
            "source_event_id": prepared.get("source_event_id"), "proposal_event_id": prepared.get("proposal_event_id"),
            "plan_schema_version": plan.get("schema_version") if plan else None,
            "attempts": attempts, "accepted": accepted, "budget": budget,
            "source_loaded": False, "proposal_loaded": False, "acceptance": False,
            "dispatch_authority": False}
