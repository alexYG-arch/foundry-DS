#!/usr/bin/env python3
"""D4a: check a Design Decision Record and its bound Plan/Scope.

Read-only. This is not a compiler, approval or execution authority.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA = "FOUNDRY_DDR_V1"
STAGES = tuple(f"S{i}" for i in range(8))
STAGE_STATUS = {"DECIDED", "DEFERRED", "NOT_APPLICABLE"}
RULE_TYPES = {"DOMAIN_RULE", "GOVERNANCE_POLICY", "HEURISTIC"}
CARRIERS = {"codex", "claude-code", "generic-agent", "human-only"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class Finding:
    def __init__(self, code: str, message: str, severity: str = "ERROR"):
        self.code, self.message, self.severity = code, message, severity

    def as_dict(self):
        return {"code": self.code, "message": self.message, "severity": self.severity}


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value) -> bool:
    return isinstance(value, list)


def _ids(rows, key, findings, label):
    seen = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            findings.append(Finding("DDR_ROW_INVALID", f"{label} entry must be an object"))
            continue
        value = row.get(key)
        if not _text(value):
            findings.append(Finding("DDR_ID_INVALID", f"{label} needs nonempty {key}"))
            continue
        if value in seen:
            findings.append(Finding("DDR_ID_DUPLICATE", f"duplicate {label} id: {value}"))
        seen.add(value)
    return seen


def _check_record(record, findings):
    required = {"schema_version", "record_id", "plan_id", "owner", "created_at", "carrier",
                "stages", "rules", "subharnesses", "checks", "gaps"}
    if not isinstance(record, dict):
        findings.append(Finding("DDR_NOT_OBJECT", "record must be an object"))
        return
    missing = required - set(record)
    extra = set(record) - required
    if missing:
        findings.append(Finding("DDR_FIELDS_MISSING", f"missing fields: {sorted(missing)}"))
    if extra:
        findings.append(Finding("DDR_FIELDS_UNSUPPORTED", f"unsupported fields: {sorted(extra)}"))
    if record.get("schema_version") != SCHEMA:
        findings.append(Finding("DDR_SCHEMA_UNSUPPORTED", f"schema_version must be {SCHEMA}"))
    if not _text(record.get("record_id")) or not str(record.get("record_id", "")).startswith("DDR-"):
        findings.append(Finding("DDR_ID_INVALID", "record_id must start with DDR-"))
    for key in ("plan_id", "owner", "created_at"):
        if not _text(record.get(key)):
            findings.append(Finding("DDR_TEXT_MISSING", f"{key} must be nonempty"))

    carrier = record.get("carrier")
    if not isinstance(carrier, dict):
        findings.append(Finding("DDR_CARRIER_INVALID", "carrier must be an object"))
    else:
        if carrier.get("carrier_id") not in CARRIERS:
            findings.append(Finding("DDR_CARRIER_UNSUPPORTED", "carrier_id is not a declared carrier"))
        limits = carrier.get("limits")
        if not _list(limits) or not limits or not all(_text(x) for x in limits):
            findings.append(Finding("DDR_CARRIER_LIMITS", "carrier.limits must be nonempty text"))

    stages = record.get("stages")
    if not isinstance(stages, dict):
        findings.append(Finding("DDR_STAGES_INVALID", "stages must be an object"))
    else:
        missing_stages = set(STAGES) - set(stages)
        extra_stages = set(stages) - set(STAGES)
        if missing_stages:
            findings.append(Finding("DDR_STAGES_MISSING", f"missing stages: {sorted(missing_stages)}"))
        if extra_stages:
            findings.append(Finding("DDR_STAGES_UNSUPPORTED", f"unsupported stages: {sorted(extra_stages)}"))
        for stage in STAGES:
            row = stages.get(stage)
            if not isinstance(row, dict):
                findings.append(Finding("DDR_STAGE_INVALID", f"{stage} must be an object"))
                continue
            if row.get("status") not in STAGE_STATUS:
                findings.append(Finding("DDR_STAGE_STATUS", f"{stage} has unsupported status"))
            if row.get("status") in {"DECIDED", "DEFERRED"} and not _text(row.get("decision")):
                findings.append(Finding("DDR_STAGE_DECISION", f"{stage} needs a decision"))
            if not _list(row.get("evidence")) or not all(_text(x) for x in row["evidence"]):
                findings.append(Finding("DDR_STAGE_EVIDENCE", f"{stage}.evidence must be a text list"))

    rules = record.get("rules")
    if not _list(rules):
        findings.append(Finding("DDR_RULES_INVALID", "rules must be a list"))
    else:
        _ids(rules, "id", findings, "rule")
        for row in rules:
            if not isinstance(row, dict):
                continue
            if row.get("type") not in RULE_TYPES:
                findings.append(Finding("DDR_RULE_TYPE", f"rule {row.get('id')} has unsupported type"))
            if not _text(row.get("text")):
                findings.append(Finding("DDR_RULE_TEXT", f"rule {row.get('id')} needs text"))
            if row.get("type") in {"DOMAIN_RULE", "GOVERNANCE_POLICY"} and not _text(row.get("enforcement")):
                findings.append(Finding("DDR_RULE_ENFORCEMENT",
                                        f"rule {row.get('id')} has no enforcement point; downgrade to HEURISTIC"))

    subharnesses = record.get("subharnesses")
    if not _list(subharnesses):
        findings.append(Finding("DDR_SUBHARNESSES_INVALID", "subharnesses must be a list"))
    else:
        _ids(subharnesses, "id", findings, "subharness")
        for row in subharnesses:
            if isinstance(row, dict):
                for key in ("reason", "alternatives"):
                    if not _text(row.get(key)):
                        findings.append(Finding("DDR_SUBHARNESS_REASON",
                                                f"subharness {row.get('id')} needs {key}"))

    checks = record.get("checks")
    if not _list(checks) or not checks:
        findings.append(Finding("DDR_CHECKS_EMPTY", "checks must be a nonempty list"))
    else:
        _ids(checks, "case_id", findings, "check")
        for row in checks:
            if not isinstance(row, dict):
                continue
            for key in ("verifier", "oracle", "independence"):
                if not _text(row.get(key)):
                    findings.append(Finding("DDR_CHECK_FIELD", f"check {row.get('case_id')} needs {key}"))

    gaps = record.get("gaps")
    if not _list(gaps):
        findings.append(Finding("DDR_GAPS_INVALID", "gaps must be a list"))
    else:
        for row in gaps:
            if not isinstance(row, dict) or any(not _text(row.get(k)) for k in ("capability", "owner", "next")):
                findings.append(Finding("DDR_GAP_INCOMPLETE", "each gap needs capability/owner/next"))


def _check_request(request, record, findings):
    if not isinstance(request, dict):
        findings.append(Finding("DDR_REQUEST_INVALID", "request must be an object"))
        return
    ir, plan = request.get("requirement_ir"), request.get("plan")
    if not isinstance(ir, dict) or not isinstance(plan, dict):
        findings.append(Finding("DDR_REQUEST_SHAPE", "request needs requirement_ir and plan"))
        return
    atoms = {a.get("atom_id") for a in ir.get("atoms", []) if isinstance(a, dict)}
    acceptance = [c for c in ir.get("acceptance_cases", []) if isinstance(c, dict)]
    negatives = [c for c in ir.get("negative_cases", []) if isinstance(c, dict)]
    if not acceptance:
        findings.append(Finding("DDR_ACCEPTANCE_EMPTY", "requirement_ir.acceptance_cases is empty"))
    case_ids = {c.get("case_id") for c in acceptance if _text(c.get("case_id"))}
    if not negatives:
        findings.append(Finding("DDR_NEGATIVE_MISSING", "requirement_ir.negative_cases is empty"))
    covered = set()
    for case in acceptance:
        if not _text(case.get("case_id")) or not case.get("acceptance_contract"):
            findings.append(Finding("DDR_CASE_CONTRACT", "each acceptance case needs case_id and acceptance_contract"))
        for atom in case.get("atom_ids", []):
            if atom not in atoms:
                findings.append(Finding("DDR_CASE_ATOM", f"case {case.get('case_id')} references unknown atom {atom}"))
            covered.add(atom)
    uncovered = atoms - covered
    if uncovered:
        findings.append(Finding("DDR_ATOM_UNCOVERED", f"atoms without acceptance case: {sorted(uncovered)}"))

    workpacks = [w for w in plan.get("workpacks", []) if isinstance(w, dict)]
    if not workpacks:
        findings.append(Finding("DDR_PLAN_EMPTY", "plan.workpacks is empty"))
    for workpack in workpacks:
        verification = workpack.get("verification")
        if not _list(verification) or not verification:
            findings.append(Finding("DDR_PLAN_VERIFICATION", f"workpack {workpack.get('workpack_id')} has no verification"))
            continue
        for row in verification:
            case_id = row.get("case_id") if isinstance(row, dict) else None
            if case_id not in case_ids:
                findings.append(Finding("DDR_PLAN_CASE_UNKNOWN", f"verification references unknown case {case_id}"))
            argv = row.get("argv") if isinstance(row, dict) else None
            if not _list(argv) or not argv or not any(str(arg).startswith("verifier://") for arg in argv):
                findings.append(Finding("DDR_PLAN_VERIFIER", f"case {case_id} needs a verifier:// argv"))
    record_checks = {c.get("case_id") for c in record.get("checks", []) if isinstance(c, dict)}
    missing_checks = case_ids - record_checks
    if missing_checks:
        findings.append(Finding("DDR_CHECK_MATRIX_GAP", f"cases without check record: {sorted(missing_checks)}"))


def _check_scope(scope, findings):
    if not isinstance(scope, dict):
        findings.append(Finding("DDR_SCOPE_INVALID", "scope must be an object"))
        return
    workspace, verifier = scope.get("workspace_root"), scope.get("verification_root")
    if not _text(workspace) or not _text(verifier):
        findings.append(Finding("DDR_SCOPE_PATHS", "scope needs workspace_root and verification_root"))
        return
    try:
        workspace_path, verifier_path = Path(workspace).resolve(), Path(verifier).resolve()
    except OSError as exc:
        findings.append(Finding("DDR_SCOPE_PATHS", f"scope path cannot resolve: {exc}"))
        return
    if workspace_path == verifier_path or workspace_path.is_relative_to(verifier_path) or verifier_path.is_relative_to(workspace_path):
        findings.append(Finding("DDR_VERIFIER_IN_WRITE_DOMAIN",
                                "verification_root and workspace_root must not contain each other"))
    if not _list(scope.get("source_read_roots")):
        findings.append(Finding("DDR_SCOPE_READ_ROOTS", "source_read_roots must be a list"))


def check(record, request=None, scope=None):
    findings = []
    _check_record(record, findings)
    if request is not None:
        _check_request(request, record, findings)
    if scope is not None:
        _check_scope(scope, findings)
    errors = [f for f in findings if f.severity == "ERROR"]
    return {
        "schema_version": "FOUNDRY_DDR_CHECK_V1",
        "status": "PASS" if not errors else "FAIL",
        "record_id": record.get("record_id") if isinstance(record, dict) else None,
        "findings": [f.as_dict() for f in findings],
        "error_count": len(errors),
        "warning_count": len(findings) - len(errors),
        "design_record_verified": False,
        "execution_started": False,
        "writes_performed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--scope", type=Path)
    args = parser.parse_args(argv)
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        request = json.loads(args.request.read_text(encoding="utf-8")) if args.request else None
        scope = json.loads(args.scope.read_text(encoding="utf-8")) if args.scope else None
        result = check(record, request, scope)
    except (OSError, ValueError) as exc:
        result = {"schema_version": "FOUNDRY_DDR_CHECK_V1", "status": "ERROR",
                  "diagnostic": str(exc), "execution_started": False, "writes_performed": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1 if result["status"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
