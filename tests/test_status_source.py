"""docs/STATUS.json is the single place status and gate numbers live."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StatusSourceTests(unittest.TestCase):
    def test_status_file_is_well_formed_and_cited_by_the_documents(self):
        status = json.loads((ROOT / "docs/STATUS.json").read_text(encoding="utf-8"))
        self.assertEqual(status["schema_version"], "FOUNDRY_STATUS_V1")
        for key in ("roadmap", "spec", "gate", "control_store"):
            self.assertIn(key, status)
        self.assertEqual(status["roadmap"]["document"], "docs/FOUNDRY_ROADMAP_2026Q4.md")
        for document in ("docs/FOUNDRY_ROADMAP_2026Q4.md", "docs/AGENT_ADAPTER_CONTRACT.md", "AGENTS.md", "docs/DOC_INDEX.md"):
            self.assertIn("STATUS.json", (ROOT / document).read_text(encoding="utf-8"), document)
        roadmap = (ROOT / "docs/FOUNDRY_ROADMAP_2026Q4.md").read_text(encoding="utf-8")
        self.assertNotIn("P3_FULL_CONTRACT_VERIFIED", roadmap)
        # The gate's platform sets are described the same way the gate defines them.
        import importlib.util
        spec = importlib.util.spec_from_file_location("gate", ROOT / "tools/check_release_source.py")
        gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
        self.assertEqual(status["gate"]["platform_sets"]["darwin"], list(gate.PLATFORM_MODULES["darwin"]))
        self.assertEqual(status["gate"]["platform_sets"]["linux"], list(gate.PLATFORM_MODULES["linux"]))

    def test_doc_index_lists_only_existing_current_documents(self):
        import re
        index = (ROOT / "docs/DOC_INDEX.md").read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)#]+)\)", index):
            self.assertTrue((ROOT / "docs" / link).is_file(), link)

    def test_update_status_writes_only_the_gate_result(self):
        with tempfile.TemporaryDirectory() as d:
            status_path = Path(d) / "STATUS.json"
            status_path.write_text((ROOT / "docs/STATUS.json").read_text(encoding="utf-8"), encoding="utf-8")
            report = Path(d) / "report.json"
            report.write_text(json.dumps({"status": "SOURCE_CHECKS_PASS", "platform_set": "linux",
                                          "tests": {"discovered": 10, "passed": 10, "skipped": [], "failures": [], "errors": []}}))
            sys.path.insert(0, str(ROOT / "tools"))
            try:
                import update_status
            finally:
                sys.path.pop(0)
            before = json.loads(status_path.read_text())
            after = update_status.update(report, date="2026-10-29", status_path=status_path)
            self.assertEqual(after["gate"]["last_local_result"]["passed"], 10)
            self.assertEqual(after["gate"]["last_local_result"]["measured_on"], "2026-10-29")
            self.assertEqual(after["updated_at"], "2026-10-29")
            self.assertEqual(after["roadmap"], before["roadmap"], "plan status stays a human decision")
            self.assertEqual(after["spec"], before["spec"])
            cli = subprocess.run([sys.executable, "-B", str(ROOT / "tools/update_status.py"), str(report),
                                  "--date", "2026-10-30", "--status", str(status_path)],
                                 capture_output=True, text=True, check=False, cwd=d)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertEqual(json.loads(status_path.read_text())["updated_at"], "2026-10-30")
            self.assertEqual(json.loads((ROOT / "docs/STATUS.json").read_text())["updated_at"], before["updated_at"])


if __name__ == "__main__":
    unittest.main()
