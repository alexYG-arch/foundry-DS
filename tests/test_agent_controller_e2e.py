"""Full prepare -> approve -> advance-build -> DSH artifact path (fake DSH)."""

from __future__ import annotations

import shutil
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_entrypoint import apply_build_request
from harness_foundry_factory.build_runtime import (
    approve_build_authorization, prepare_build_authorization, record_source_snapshot,
)
from harness_foundry_factory.store import ControlEventStore
from tests.build_review_fixture import reviewed_document

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests/fixtures/agents/controller-dsh.sh"
NOW = datetime.now(timezone.utc).isoformat()


class FullAgentFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"; (self.workspace / "src").mkdir(parents=True)
        self.source = self.root / "source"; self.source.mkdir()
        self.verifier = self.root / "verifier"; self.verifier.mkdir()
        (self.source / "brief.md").write_text("Build proof.txt. Keep it offline.\n")
        (self.verifier / "check.py").write_text("print('ok')\n")
        self.dsh_home = self.root / "dsh-home"; (self.dsh_home / "foundry").mkdir(parents=True)
        (self.dsh_home / "foundry" / "deepseek.key").write_text("fake-full-flow-key\n")
        (self.dsh_home / "foundry" / "deepseek.key").chmod(0o600)
        self.dsh = self.workspace / "dsh"; shutil.copy2(FAKE, self.dsh)
        self.dsh.chmod(self.dsh.stat().st_mode | stat.S_IXUSR)
        self.ir = {
            "program_id": "P2-FULL-FLOW", "revision": 1,
            "target": {"id": "P2", "mission": "Full 1.3 flow.", "scope": ["proof"], "non_goals": []},
            "sources": [{"source_id": "BRIEF", "path_or_uri": "brief.md", "loaded_completely": True}],
            "atoms": [{"atom_id": "A1", "text_or_lossless_paraphrase": "Write proof.",
                       "source_id": "BRIEF", "source_locator": "L1"}],
            "acceptance_cases": [{"case_id": "C1", "atom_ids": ["A1"], "description": "proof exists",
                                   "acceptance_contract": {"source_id": "BRIEF", "source_locator": "L1"}}],
            "negative_cases": [],
        }
        self.plan = {"schema_version": "1.3", "plan_id": "P2-FULL", "revision": 1, "requirement_revision": 1,
            "workpacks": [{"workpack_id": "IMPLEMENT", "job_id": "IMPLEMENT", "executor": "AGENT",
                "agent": {"adapter": "dsh-headless", "adapter_version": "1"},
                "goal": "Write proof.txt.", "depends_on": [], "atom_ids": ["A1"],
                "inputs": [{"kind": "SOURCE", "id": "BRIEF"}],
                "artifacts": [{"artifact_id": "PROOF", "path": "proof.txt"}],
                "verification": [{"case_id": "C1", "argv": ["true"], "artifact_ids": ["PROOF"]}]}]}
        self.scope = {"scope_version": "1.3",
            "agents": {"dsh": {"adapter": "dsh-headless", "executable": str(self.dsh),
                               "dsh_home": str(self.dsh_home)}},
            "sandbox": {"provider": "seatbelt", "network": {"agent_egress": "NONE", "task_network": "NONE"}},
            "usage_accounting": "UNKNOWN", "workspace_root": str(self.workspace),
            "source_read_roots": [str(self.source)], "verification_root": str(self.verifier),
            "task_write_roots": {"IMPLEMENT": [str(self.workspace)]},
            "executables": {"true": "/usr/bin/true"}, "max_attempts": 3, "max_task_attempts": 2,
            "command_timeout_seconds": 30, "expires_at": "2099-01-01T00:00:00Z"}
        self.store = ControlEventStore(self.root / "control.sqlite3", storage_format="REVISION_V1")
        self.review = reviewed_document(self.source, path=self.source / "brief.md", source_id="BRIEF")
        self.program = self.ir["program_id"]

    def kw(self, key, revision):
        return {"expected_revision": revision, "idempotency_key": key, "created_at": NOW}

    def build_events(self):
        proposal = record_build_plan_proposal(self.store, self.ir, self.plan,
                                              document_review=self.review, **self.kw("proposal", 0))
        source = record_source_snapshot(self.store, self.program, proposal["event_id"], self.source,
            [{"source_id": "BRIEF", "path": "brief.md"}], **self.kw("source", 1))
        prepared = prepare_build_authorization(self.store, self.program, proposal["event_id"], source["event_id"],
            self.scope, **self.kw("prepare", 2))
        approve_build_authorization(self.store, self.program, prepared["event_id"],
            human_message_ref="TEST-ONLY-FULL-FLOW", **self.kw("approve", 3))
        return prepared["event_id"]

    def test_advance_build_13_full_flow(self):
        prepared_id = self.build_events()
        result = apply_build_request("advance-build", {"program_id": self.program, "prepared_event_id": prepared_id,
            "expected_revision": 4}, self.root / "control.sqlite3")
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(result["agent_controller"], "EXPERIMENTAL_1_3")
        self.assertEqual((self.workspace / "proof.txt").read_text(), "proof.txt")


if __name__ == "__main__":
    unittest.main()
