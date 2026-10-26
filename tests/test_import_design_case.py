"""D0.1 mapping test: JSONL case -> manifest -> RSI_CASE_V1 import."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness_foundry_factory.rsi_cases import import_case, read_json
from tools.import_design_case import load_case, material


class DesignCaseMapperTests(unittest.TestCase):
    def test_maps_one_case_and_imports_material(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            case = {
                "case_id": "DESIGN-999", "title": "Test design case", "stage": "S6",
                "kind": "REAL_BUILD", "status": "OPEN", "source": {"document": "TEST.md", "section": "1"},
                "symptom": "symptom", "root_cause": "cause", "design_decision": "decision",
                "pattern": "P1", "evidence": ["a"], "verification": "check",
            }
            cases = root / "cases.jsonl"; cases.write_text(json.dumps(case) + "\n")
            loaded = load_case(cases, "DESIGN-999")
            self.assertEqual(loaded["case_id"], "DESIGN-999")
            material_dir = root / "material"; material_dir.mkdir()
            material_path = material_dir / "DESIGN-999.md"; material_path.write_text(material(loaded))
            manifest = {"case_id": loaded["case_id"], "goal": loaded["title"],
                        "requirements": [loaded["design_decision"]],
                        "sources": [{"source_id": "D0-CASE", "kind": "MATERIAL",
                                     "path": "DESIGN-999.md", "context": {"phase": "D0"}}]}
            imported = import_case(manifest, material_dir)
            self.assertEqual(imported["import_status"], "COMPLETE")
            self.assertEqual(imported["case_id"], "DESIGN-999")
            self.assertFalse(imported["acceptance_verified"])

    def test_unknown_or_incomplete_case_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cases.jsonl"; path.write_text('{"case_id":"DESIGN-1"}\n')
            with self.assertRaises(ValueError):
                load_case(path, "DESIGN-1")
            with self.assertRaises(ValueError):
                load_case(path, "DESIGN-NOT-FOUND")


if __name__ == "__main__":
    unittest.main()
