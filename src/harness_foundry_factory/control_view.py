"""A3-read v2: lightweight, revision-preserving control view.

The dispatch boundary `_current` still owns full source/review validation. This
view is for monitoring, cancellation and budget/attempt surfaces that do not
need source or proposal bodies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .build_rebind import superseding_prepared
from .build_state import attempt_budget, project_budget_attempts, project_execution_state
from .build_types import RequestValidationError

AUTH_TYPES = ("BUILD_AUTHORIZATION_PREPARED", "BUILD_AUTHORIZATION_APPROVED", "BUILD_AUTHORIZATION_REVOKED")
ATTEMPT_TYPES = ("BUILD_ATTEMPT_STARTED", "BUILD_ATTEMPT_FINISHED", "BUILD_ATTEMPT_RECOVERED",
                 "BUILD_ATTEMPT_RESOLVED", "BUILD_ACCEPTANCE_INVALIDATED")


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RequestValidationError("control view expiry requires an absolute timezone")
    return parsed.astimezone(timezone.utc)


def build_control_view(store, program_id: str, prepared_id: str, *, now=None) -> dict[str, Any]:
    prepared_event = store.get_event(program_id, prepared_id)
    if prepared_event is None or prepared_event["event_type"] != "BUILD_AUTHORIZATION_PREPARED":
        raise RequestValidationError("control view preparation is missing")
    prepared = prepared_event["payload"]
    auth = store.list_events_by_types(program_id, AUTH_TYPES)
    attempts_events = store.list_events_by_types(program_id, ATTEMPT_TYPES)
    events = sorted(auth + attempts_events, key=lambda row: row["stream_revision"])
    approved = any(row["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                   and row["payload"].get("prepared_event_id") == prepared_id for row in auth)
    revoked = any(row["event_type"] == "BUILD_AUTHORIZATION_REVOKED"
                  and row["payload"].get("prepared_event_id") == prepared_id for row in auth)
    superseded = superseding_prepared(auth, prepared_id) is not None
    expires = _utc(prepared["scope"]["expires_at"])
    current = now or datetime.now(timezone.utc)
    state = ("SUPERSEDED" if superseded else "REVOKED" if revoked else
             "EXPIRED" if current >= expires else "APPROVED" if approved else "APPROVAL_REQUIRED")
    attempts, accepted = project_execution_state(events, prepared_id)
    budget = attempt_budget(prepared["scope"], list(project_budget_attempts(events, prepared_id).values()))
    return {"schema_version": "CONTROL_VIEW_V2", "program_id": program_id,
            "prepared_event_id": prepared_id, "stream_revision": store.event_count(program_id),
            "state": state, "approved": approved, "revoked": revoked,
            "superseded": superseded, "expires_at": prepared["scope"]["expires_at"],
            "source_event_id": prepared["source_event_id"], "proposal_event_id": prepared["proposal_event_id"],
            "attempts": attempts, "accepted": accepted, "budget": budget,
            "source_loaded": False, "proposal_loaded": False, "acceptance": False}
