"""A4: non-recursive current view over a frozen baseline, delta and evidence."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

HANDOFF_SCHEMA = "RSI_CURRENT_VIEW_V1"


class HandoffError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise HandoffError(message)


def _reference(row, label):
    _require(isinstance(row, Mapping), f"{label} must be an object")
    _require(isinstance(row.get("id"), str) and row["id"], f"{label}.id is required")
    _require(isinstance(row.get("sha256"), str) and len(row["sha256"]) == 64,
             f"{label}.sha256 must be a SHA-256")
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
                       ("evidence", "Evidence"), ("pending", "Pending"), ("history_refs", "History references")):
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
