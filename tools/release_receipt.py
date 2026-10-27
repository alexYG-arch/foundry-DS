#!/usr/bin/env python3
"""Bind release evidence to one commit/package; never silently grants release.

The receipt is deliberately separate from source diagnostics. It fails closed
when a required artifact or external acceptance is missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _regression(path):
    text = Path(path).read_text(encoding="utf-8")
    ran = re.search(r"Ran (\d+) tests", text)
    ok = "OK" in text and "FAILED" not in text
    failures = int((re.search(r"failures=(\d+)", text) or [None, "0"])[1]) if "failures=" in text else 0
    errors = int((re.search(r"errors=(\d+)", text) or [None, "0"])[1]) if "errors=" in text else 0
    skipped = int((re.search(r"skipped=(\d+)", text) or [None, "0"])[1]) if "skipped=" in text else 0
    return {"status": "PASS" if ok and failures == 0 and errors == 0 else "FAIL",
            "tests": int(ran.group(1)) if ran else 0, "failures": failures,
            "errors": errors, "skipped": skipped}


def build(*, commit, package, source_gate, regression_text, two_cases, spec, publication,
          native_codex, waivers=(), scope="LOCAL_RELEASE", physical_sibling="NOT_AVAILABLE"):
    findings = []
    package = Path(package).resolve()
    actual_sha = _sha(package)
    gate = _load(source_gate)
    regression = _regression(regression_text)
    cases = _load(two_cases)
    spec_value = _load(spec)
    pub = _load(publication)
    if spec_value.get("status") != "PASS":
        findings.append("spec lock is not PASS")
    if not isinstance(cases, list) or not cases or not all(row.get("accepted") is True and row.get("verifier") == "PASS" for row in cases):
        findings.append("same-package cases are not all accepted/verified")
    if regression["status"] != "PASS":
        findings.append("full regression is not PASS/0F0E")
    if gate.get("status") != "SOURCE_CHECKS_PASS":
        findings.append("source gate is not PASS")
    if native_codex not in {"PASS", "DEFERRED_BY_USER"}:
        findings.append("native Codex acceptance is missing")
    if native_codex == "DEFERRED_BY_USER" and not waivers:
        findings.append("Codex deferral requires an explicit waiver")
    limits = []
    if native_codex == "DEFERRED_BY_USER": limits.append("NATIVE_CODEX_ACCEPTANCE_DEFERRED_BY_USER")
    if physical_sibling != "PASS": limits.append("PHYSICAL_SIBLING_SPEC_NOT_AVAILABLE")
    expected = pub.get("commit")
    if not expected:
        findings.append("publication commit is missing")
    # The caller supplies the package digest in publication/package evidence.
    recorded_sha = pub.get("package_sha256")
    if not recorded_sha or recorded_sha != actual_sha:
        findings.append("package digest does not match publication evidence")
    status = "ACCEPTED" if not findings and native_codex == "PASS" and physical_sibling == "PASS" else (
        "ACCEPTED_WITH_LIMITS" if not findings and waivers else "REJECTED")
    local = status in {"ACCEPTED", "ACCEPTED_WITH_LIMITS"}
    return {"schema_version": "RELEASE_RECEIPT_V1", "status": status,
            "scope": scope, "limits": limits,
            "release_accepted": status == "ACCEPTED",
            "local_release_accepted": local,
            "commit": commit, "package": {"path": str(package), "sha256": actual_sha},
            "source_gate": {"status": gate.get("status"), "modules": len(gate.get("required_modules", [])),
                            "tests": gate.get("tests", {}).get("discovered")},
            "full_regression": regression,
            "same_package_two_cases": {"status": "PASS" if not findings or cases else "FAIL", "cases": cases},
            "spec": spec_value, "physical_sibling": physical_sibling,
            "publication": pub, "native_codex": native_codex,
            "waivers": list(waivers), "findings": findings}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--commit", required=True)
    p.add_argument("--package", required=True)
    p.add_argument("--source-gate", required=True)
    p.add_argument("--regression", required=True)
    p.add_argument("--two-cases", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--native-codex", required=True, choices=("PASS", "DEFERRED_BY_USER", "MISSING"))
    p.add_argument("--physical-sibling", default="NOT_AVAILABLE", choices=("PASS", "NOT_AVAILABLE"))
    p.add_argument("--waiver", action="append", default=[])
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    result = build(commit=args.commit, package=args.package, source_gate=args.source_gate,
                   regression_text=args.regression, two_cases=args.two_cases, spec=args.spec,
                   publication=args.publication, native_codex=args.native_codex, waivers=args.waiver,
                   physical_sibling=args.physical_sibling)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ACCEPTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
