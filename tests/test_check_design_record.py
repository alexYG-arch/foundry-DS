"""D4a design-record checker tests; synthetic, no execution."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ddr_check", ROOT / "tools/check_design_record.py")
ddr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ddr)


def record_fixture():
    return {
        "schema_version": "FOUNDRY_DDR_V1",
        "record_id": "DDR-TEST-001",
        "plan_id": "PLAN-TEST",
        "owner": "maintainer",
        "created_at": "2026-10-26T00:00:00+08:00",
        "carrier": {"carrier_id": "codex", "limits": ["skills are convention"]},
        "stages": {
            **{f"S{i}": {"status": "DECIDED", "decision": f"decision {i}", "evidence": ["doc"]} for i in range(7)},
            "S7": {"status": "NOT_APPLICABLE", "decision": "not in scope", "evidence": []},
        },
        "rules": [{"id": "RULE-1", "type": "DOMAIN_RULE", "text": "verifier outside writes",
                   "enforcement": "checks[CASE-1]"}],
        "subharnesses": [],
        "checks": [{"case_id": "CASE-1", "verifier": "verifier://check.py",
                    "oracle": "expected.json", "independence": "WRITE_DOMAIN_EXCLUDED",
                    "negative": "CASE-1-NEG"}],
        "gaps": [],
    }


def request_fixture():
    return {
        "requirement_ir": {
            "atoms": [{"atom_id": "A1", "text_or_lossless_paraphrase": "behavior", "source_id": "S"}],
            "acceptance_cases": [{"case_id": "CASE-1", "atom_ids": ["A1"],
                                  "acceptance_contract": {"source_id": "S", "source_locator": "L1"}}],
            "negative_cases": [{"case_id": "CASE-1-NEG", "atom_ids": ["A1"],
                                "acceptance_contract": {"source_id": "S", "source_locator": "L2"}}],
        },
        "plan": {"schema_version": "1.2", "plan_id": "PLAN-TEST", "revision": 1,
                 "requirement_revision": 1, "workpacks": [{
                     "workpack_id": "W1", "job_id": "J1", "executor": "LOCAL",
                     "local_argv": ["python", "-V"], "goal": "run", "depends_on": [],
                     "atom_ids": ["A1"], "artifacts": [],
                     "verification": [{"case_id": "CASE-1", "artifact_ids": [],
                                       "argv": ["python", "verifier://check.py"]}],
                 }]},
    }


class DesignRecordCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.scope = {"workspace_root": str(root / "ws"), "verification_root": str(root / "verifier"),
                      "source_read_roots": []}
        (root / "ws").mkdir()
        (root / "verifier").mkdir()

    def test_passes_valid_record_and_bindings(self):
        result = ddr.check(record_fixture(), request_fixture(), self.scope)
        self.assertEqual(result["status"], "PASS", json.dumps(result, ensure_ascii=False, indent=2))
        self.assertFalse(result["design_record_verified"])

    def test_rule_without_enforcement_fails(self):
        record = record_fixture()
        record["rules"][0]["enforcement"] = ""
        self.assertEqual(ddr.check(record)["status"], "FAIL")

    def test_missing_stage_fails(self):
        record = record_fixture()
        del record["stages"]["S3"]
        self.assertEqual(ddr.check(record)["status"], "FAIL")

    def test_carrier_limits_required(self):
        record = record_fixture()
        record["carrier"]["limits"] = []
        self.assertEqual(ddr.check(record)["status"], "FAIL")

    def test_subharness_reason_required(self):
        record = record_fixture()
        record["subharnesses"] = [{"id": "SUB-1", "reason": "", "alternatives": "none"}]
        self.assertEqual(ddr.check(record)["status"], "FAIL")

    def test_check_matrix_gap_fails(self):
        record = record_fixture()
        record["checks"] = []
        self.assertEqual(ddr.check(record, request_fixture())["status"], "FAIL")

    def test_negative_cases_required(self):
        request = request_fixture()
        request["requirement_ir"]["negative_cases"] = []
        self.assertEqual(ddr.check(record_fixture(), request)["status"], "FAIL")

    def test_verifier_inside_workspace_fails(self):
        scope = copy.deepcopy(self.scope)
        scope["verification_root"] = str(Path(scope["workspace_root"]) / "verifier")
        self.assertEqual(ddr.check(record_fixture(), None, scope)["status"], "FAIL")

    def test_plan_case_without_verifier_fails(self):
        request = request_fixture()
        request["plan"]["workpacks"][0]["verification"][0]["argv"] = ["python", "check.py"]
        self.assertEqual(ddr.check(record_fixture(), request)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
