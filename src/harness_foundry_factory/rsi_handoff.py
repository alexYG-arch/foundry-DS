"""A4: non-recursive current view over a frozen baseline, delta and evidence."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

HANDOFF_SCHEMA = "RSI_CURRENT_VIEW_V1"


class HandoffError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise HandoffError(message)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECTIONS = ("changes", "affected_assertions", "evidence", "history_refs", "pending", "limitations")


def _reference(row, label):
    _require(isinstance(row, Mapping), f"{label} must be an object")
    _require(isinstance(row.get("id"), str) and row["id"], f"{label}.id is required")
    _require(isinstance(row.get("sha256"), str) and _SHA256_RE.fullmatch(row["sha256"]) is not None,
             f"{label}.sha256 must be a lowercase hex SHA-256")
    _require(not any(key in row for key in ("text", "body", "document")),
             f"{label} must be a reference, not embedded report text")
    return {"id": row["id"], "sha256": row["sha256"],
            **{key: row[key] for key in ("uri", "revision") if key in row}}


def build_current_view(*, baseline, changes, affected_assertions, evidence,
                       history_refs=(), pending=(), limitations=()):
    """Build a handoff without embedding previous reports' full text."""
    base = _reference(baseline, "baseline")
    for label, rows in (("changes", changes), ("affected_assertions", affected_assertions),
                        ("evidence", evidence), ("pending", pending), ("limitations", limitations)):
        _require(isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)), f"{label} must be a list")
    refs = [_reference(row, "history_ref") for row in history_refs]
    return {"schema_version": HANDOFF_SCHEMA, "baseline": base,
            "changes": list(changes), "affected_assertions": list(affected_assertions),
            "evidence": list(evidence), "history_refs": refs,
            "pending": list(pending), "limitations": list(limitations),
            "history_content_embedded": False, "acceptance": False}


def render_markdown(view):
    lines = ["# Current view", "", f"Baseline: `{view['baseline']['id']}` `{view['baseline']['sha256']}`", ""]
    for key, title in (("changes", "Changes"), ("affected_assertions", "Affected assertions"),
                       ("evidence", "Evidence"), ("pending", "Pending"), ("limitations", "Limitations"),
                       ("history_refs", "History references")):
        lines.append(f"## {title}")
        if not view[key]:
            lines.append("- none")
        for row in view[key]:
            if isinstance(row, Mapping):
                lines.append("- " + ", ".join(f"{k}={v}" for k, v in row.items()))
            else:
                lines.append(f"- {row}")
        lines.append("")
    return "\n".join(lines)


def impact_map(changes, affected_assertions):
    """Return the declared change -> assertion relation, without inventing one."""
    rows = []
    for change in changes:
        change_id = change.get("id") if isinstance(change, Mapping) else None
        for assertion in affected_assertions:
            if isinstance(assertion, Mapping) and change_id in assertion.get("change_ids", ()):
                rows.append({"change_id": change_id, "assertion_id": assertion.get("id"),
                             "status": assertion.get("status", "PENDING")})
    return rows


def paginate(view, section, offset=0, limit=50):
    if section not in SECTIONS:
        raise HandoffError("unknown current-view section")
    if type(offset) is not int or type(limit) is not int or offset < 0 or limit <= 0:
        raise HandoffError("offset/limit must be nonnegative/positive integers")
    rows = view[section]
    return {"section": section, "offset": offset, "limit": limit,
            "total": len(rows), "items": rows[offset:offset + limit],
            "has_more": offset + limit < len(rows)}


def hydrate_history(view, loader):
    """Resolve history references through caller-supplied read-only loader."""
    resolved = []
    for reference in view["history_refs"]:
        value = loader(reference)
        resolved.append({"reference": reference, "loaded": value is not None, "value": value})
    return resolved


def diff_views(previous, current):
    """Compare two current-view envelopes by identity, never by embedded text."""
    if previous.get("schema_version") != HANDOFF_SCHEMA or current.get("schema_version") != HANDOFF_SCHEMA:
        raise HandoffError("both views must use RSI_CURRENT_VIEW_V1")
    result = {"schema_version": "RSI_CURRENT_VIEW_DIFF_V1", "sections": {}, "acceptance": False}
    for section in SECTIONS:
        old = {row.get("id"): row for row in previous[section] if isinstance(row, Mapping) and row.get("id")}
        new = {row.get("id"): row for row in current[section] if isinstance(row, Mapping) and row.get("id")}
        result["sections"][section] = {"added": sorted(set(new) - set(old)),
                                       "removed": sorted(set(old) - set(new)),
                                       "changed": sorted(key for key in set(old) & set(new) if old[key] != new[key])}
    result["baseline_changed"] = previous["baseline"] != current["baseline"]
    return result
