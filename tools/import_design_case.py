#!/usr/bin/env python3
"""D0.1: map one design-case JSONL record to an RSI_CASE_V1 manifest.

Writes a derived MATERIAL source and a manifest; it does not run a model or
mutate Foundry control state. The derived source is evidence text, not a claim
of independent verification.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from harness_foundry_factory.build_types import canonical_json  # noqa: E402

REQUIRED = ("case_id", "title", "stage", "kind", "status", "source", "symptom",
            "root_cause", "design_decision", "pattern", "evidence", "verification")


def load_case(path: Path, case_id: str) -> dict:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict) and value.get("case_id") == case_id:
            missing = [key for key in REQUIRED if key not in value]
            if missing:
                raise ValueError("case is missing fields: " + ", ".join(missing))
            return value
    raise ValueError("case not found: " + case_id)


def material(case: dict) -> str:
    source = case["source"]
    lines = [
        "# " + case["case_id"] + " — " + case["title"],
        "stage: " + str(case["stage"]),
        "kind: " + str(case["kind"]),
        "status: " + str(case["status"]),
        "source: " + json.dumps(source, ensure_ascii=False, sort_keys=True),
        "symptom: " + str(case["symptom"]),
        "root_cause: " + str(case["root_cause"]),
        "design_decision: " + str(case["design_decision"]),
        "pattern: " + str(case["pattern"]),
        "evidence: " + json.dumps(case["evidence"], ensure_ascii=False, sort_keys=True),
        "verification: " + str(case["verification"]),
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True, help="manifest path; never overwritten")
    parser.add_argument("--material-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        case = load_case(args.cases.resolve(strict=True), args.case_id)
        material_dir = args.material_dir.resolve()
        material_dir.mkdir(parents=True, exist_ok=True)
        material_path = material_dir / (case["case_id"] + ".md")
        if material_path.exists() or args.output.exists():
            raise ValueError("refusing to overwrite an existing derived case or manifest")
        material_path.write_text(material(case), encoding="utf-8")
        manifest = {
            "case_id": case["case_id"],
            "goal": case["title"],
            "requirements": [case["design_decision"]],
            "sources": [{"source_id": "D0-CASE", "kind": "MATERIAL",
                         "path": material_path.name,
                         "context": {"phase": "D0", "task_id": case["case_id"]}}],
        }
        args.output.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "diagnostic": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": "MAPPED", "case_id": case["case_id"], "manifest": str(args.output),
                      "material": str(material_path), "acceptance_verified": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
