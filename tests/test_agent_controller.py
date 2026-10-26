"""Experimental 1.3 controller dispatch through a fake DSH adapter."""

from __future__ import annotations

import json
import shutil
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness_foundry_factory.agents.agent_controller import AgentBuildController
from harness_foundry_factory.build_entrypoint import apply_build_request
from harness_foundry_factory.store import ControlEventStore

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests/fixtures/agents/controller-dsh.sh"


class FlakyAdapter:
    def __init__(self, workspace, fail_first=True, always_fail=False):
        self.workspace = Path(workspace)
        self.fail_first = fail_first
        self.always_fail = always_fail
        self.calls = 0
        self.prompts = []

    def run(self, request, *, before_dispatch, **hooks):
        self.calls += 1
        self.prompts.append(request.prompt)
        (self.workspace / "proof.txt").write_text("proof.txt")
        failed = self.always_fail or (self.fail_first and self.calls == 1)
        return {"status": "FAIL" if failed else "PASS", "adapter_id": "flaky",
                "workload_started": True, "workpack_accepted": False}


class AgentControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"; self.workspace.mkdir()
        self.verifier = self.root / "verifier"; self.verifier.mkdir()
        self.dsh_home = self.root / "dsh-home"; self.dsh_home.mkdir()
        key_dir = self.dsh_home / "foundry"; key_dir.mkdir()
        self.key = key_dir / "deepseek.key"; self.key.write_text("fake-controller-key\n"); self.key.chmod(0o600)
        self.dsh = self.workspace / "dsh"; shutil.copy2(FAKE, self.dsh)
        self.dsh.chmod(self.dsh.stat().st_mode | stat.S_IXUSR)
        self.plan = {
            "schema_version": "1.3", "plan_id": "P", "revision": 1, "requirement_revision": 1,
            "workpacks": [{
                "workpack_id": "IMPLEMENT", "job_id": "IMPLEMENT", "executor": "AGENT",
                "agent": {"adapter": "dsh-headless", "adapter_version": "1"},
                "goal": "Write proof.txt.", "depends_on": [], "atom_ids": ["A1"],
                "inputs": [], "artifacts": [{"artifact_id": "PROOF", "path": "proof.txt"}],
                "verification": [{"case_id": "C1", "argv": ["true"], "artifact_ids": ["PROOF"]}],
            }],
        }
        self.scope = {
            "scope_version": "1.3",
            "agents": {"dsh": {"adapter": "dsh-headless", "executable": str(self.dsh),
                               "dsh_home": str(self.dsh_home)}},
            "sandbox": {"provider": "seatbelt", "network": {"agent_egress": "NONE", "task_network": "NONE"}},
            "usage_accounting": "UNKNOWN", "workspace_root": str(self.workspace),
            "source_read_roots": [str(self.workspace)], "verification_root": str(self.verifier),
            "task_write_roots": {"IMPLEMENT": [str(self.workspace)]},
            "executables": {"true": "/usr/bin/true"}, "max_attempts": 3, "max_task_attempts": 2,
            "command_timeout_seconds": 30, "expires_at": "2099-01-01T00:00:00Z",
        }
        self.store = ControlEventStore(self.root / "control.sqlite3", storage_format="REVISION_V1")
        self.program = "P2-AGENT-CONTROLLER"
        now = datetime.now(timezone.utc).isoformat()
        self.prepared = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": self.scope, "plan": self.plan}}], expected_revision=0,
            idempotency_key="prepare", created_at=now, require_new=True)[0]
        self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED",
            "payload": {"prepared_event_id": self.prepared["event_id"]}}], expected_revision=1,
            idempotency_key="approve", created_at=now, require_new=True)

    def test_controller_dispatches_dsh_and_accepts_artifact(self):
        result = AgentBuildController(self.store, self.program).advance(self.prepared["event_id"])
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(result["accepted_workpacks"], ["IMPLEMENT"])
        self.assertEqual((self.workspace / "proof.txt").read_text(), "proof.txt")
        events = self.store.list_events(self.program)
        self.assertEqual([row["event_type"] for row in events[-2:]],
                         ["BUILD_ATTEMPT_STARTED", "BUILD_ATTEMPT_FINISHED"])
        self.assertFalse(result["harness_e2e_verified"])

    def test_advance_build_routes_13_prepared_event_to_agent_controller(self):
        result = apply_build_request("advance-build", {
            "program_id": self.program, "prepared_event_id": self.prepared["event_id"],
            "expected_revision": len(self.store.list_events(self.program)),
        }, self.root / "control.sqlite3")
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(result["agent_controller"], "EXPERIMENTAL_1_3")
        self.assertEqual((self.workspace / "proof.txt").read_text(), "proof.txt")

    def test_controller_retries_rejected_attempt(self):
        adapter = FlakyAdapter(self.workspace, fail_first=True)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(self.prepared["event_id"])
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(adapter.calls, 2)
        self.assertEqual(result["attempts_used"], 2)
        statuses = [row["payload"]["status"] for row in self.store.list_events(self.program)
                    if row["event_type"] == "BUILD_ATTEMPT_FINISHED"]
        self.assertEqual(statuses, ["REJECTED", "ACCEPTED"])
        self.assertIn("Previous attempt was rejected", adapter.prompts[1])

    def test_controller_task_budget_exhaustion(self):
        adapter = FlakyAdapter(self.workspace, always_fail=True)
        scope = json.loads(json.dumps(self.scope))
        scope["max_task_attempts"] = 1
        now = datetime.now(timezone.utc).isoformat()
        revision = len(self.store.list_events(self.program))
        prepared = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": scope, "plan": self.plan}}], expected_revision=revision,
            idempotency_key="prepare-budget", created_at=now, require_new=True)[0]
        self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED",
            "payload": {"prepared_event_id": prepared["event_id"]}}], expected_revision=revision + 1,
            idempotency_key="approve-budget", created_at=now, require_new=True)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(prepared["event_id"])
        self.assertEqual(result["status"], "TASK_REPAIR_BUDGET_EXHAUSTED", result)
        self.assertEqual(adapter.calls, 1)

    def test_controller_requires_approval(self):
        other = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": self.scope, "plan": self.plan}}], expected_revision=2,
            idempotency_key="prepare-2", created_at=datetime.now(timezone.utc).isoformat(), require_new=True)[0]
        with self.assertRaises(ValueError):
            AgentBuildController(self.store, self.program).advance(other["event_id"])


if __name__ == "__main__":
    unittest.main()
