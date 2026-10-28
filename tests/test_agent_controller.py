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


class StagingAdapter:
    def __init__(self):
        self.calls = 0
    def run(self, request, *, before_dispatch, **hooks):
        self.calls += 1
        scope = request.command.scope
        (Path(scope.cwd) / "proof.txt").write_text("CAS_CONTROLLER_OK")
        return {"status": "PASS", "adapter_id": "staging", "workload_started": True,
                "workpack_accepted": False}


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
        self.assertEqual(result["agent_sandbox_enforcement"], "NATIVE")
        self.assertEqual(result["task_sandbox_provider"], "seatbelt")

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
        repairs = [row for row in self.store.list_events(self.program)
                   if row["event_type"] == "BUILD_AGENT_REPAIR_REQUESTED"]
        self.assertEqual(len(repairs), 1)
        self.assertTrue(repairs[0]["payload"]["failed_attempt_id"].startswith("AGENT-ATTEMPT-"))

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

    def test_controller_holds_unresolved_started_attempt(self):
        revision = len(self.store.list_events(self.program))
        now = datetime.now(timezone.utc).isoformat()
        self.store.append_batch(self.program, [{"event_type": "BUILD_ATTEMPT_STARTED",
            "payload": {"prepared_event_id": self.prepared["event_id"], "attempt_id": "A-STUCK",
                        "workpack_id": "IMPLEMENT", "job_id": "IMPLEMENT"}}],
            expected_revision=revision, idempotency_key="stuck", created_at=now, require_new=True)
        adapter = FlakyAdapter(self.workspace)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(self.prepared["event_id"])
        self.assertEqual(result["status"], "HELD_UNRESOLVED_ATTEMPT", result)
        self.assertEqual(adapter.calls, 0)

    def test_controller_recovers_already_accepted_task(self):
        revision = len(self.store.list_events(self.program))
        now = datetime.now(timezone.utc).isoformat()
        binding = {"prepared_event_id": self.prepared["event_id"], "attempt_id": "A-DONE",
                   "workpack_id": "IMPLEMENT", "job_id": "IMPLEMENT"}
        self.store.append_batch(self.program, [{"event_type": "BUILD_ATTEMPT_STARTED", "payload": binding}],
            expected_revision=revision, idempotency_key="done-start", created_at=now, require_new=True)
        self.store.append_batch(self.program, [{"event_type": "BUILD_ATTEMPT_FINISHED",
            "payload": {**binding, "status": "ACCEPTED", "artifacts": {}}}],
            expected_revision=revision + 1, idempotency_key="done-finish", created_at=now, require_new=True)
        adapter = FlakyAdapter(self.workspace)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(self.prepared["event_id"])
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(result["accepted_workpacks"], ["IMPLEMENT"])
        self.assertEqual(adapter.calls, 0)

    def test_controller_holds_accepted_artifact_drift(self):
        revision = len(self.store.list_events(self.program))
        now = datetime.now(timezone.utc).isoformat()
        binding = {"prepared_event_id": self.prepared["event_id"], "attempt_id": "A-DRIFT",
                   "workpack_id": "IMPLEMENT", "job_id": "IMPLEMENT"}
        self.store.append_batch(self.program, [{"event_type": "BUILD_ATTEMPT_STARTED", "payload": binding}],
            expected_revision=revision, idempotency_key="drift-start", created_at=now, require_new=True)
        self.store.append_batch(self.program, [{"event_type": "BUILD_ATTEMPT_FINISHED",
            "payload": {**binding, "status": "ACCEPTED",
                        "artifacts": {"PROOF": {"path": "proof.txt", "size": 1, "sha256": "0" * 64}}}}],
            expected_revision=revision + 1, idempotency_key="drift-finish", created_at=now, require_new=True)
        (self.workspace / "proof.txt").write_text("drifted")
        adapter = FlakyAdapter(self.workspace)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(self.prepared["event_id"])
        self.assertEqual(result["status"], "HELD_ACCEPTED_ARTIFACT_DRIFT", result)
        self.assertEqual(adapter.calls, 0)

    def test_controller_factory_builds_api_adapter_without_codex(self):
        key = self.root / "api.key"
        key.write_text("fake-api-key\n")
        key.chmod(0o600)
        definition = {"adapter": "deepseek-api", "base_url": "http://127.0.0.1:1/v1",
                      "key_file": str(key), "model": {"name": "deepseek-chat"}}
        adapter = AgentBuildController(self.store, self.program)._default_adapter(
            {"agent": {"adapter": "deepseek-api"}}, {"agents": {"api": definition}})
        self.assertEqual(adapter.capabilities.adapter_id, "deepseek-api")
        self.assertEqual(adapter.capabilities.sandbox, "PROVIDER")

    def test_controller_cas_ingests_staging_and_accepts_hash(self):
        import shutil as _shutil
        staging = self.root / "staging"; staging.mkdir()
        cas = self.root / "cas"; cas.mkdir()
        scope = json.loads(json.dumps(self.scope))
        scope.update(staging_root=str(staging), cas_root=str(cas))
        now = datetime.now(timezone.utc).isoformat()
        revision = len(self.store.list_events(self.program))
        prepared = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": scope, "plan": self.plan}}], expected_revision=revision,
            idempotency_key="cas-prepare", created_at=now, require_new=True)[0]
        self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED",
            "payload": {"prepared_event_id": prepared["event_id"]}}], expected_revision=revision + 1,
            idempotency_key="cas-approve", created_at=now, require_new=True)
        adapter = StagingAdapter()
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(prepared["event_id"])
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        self.assertEqual(adapter.calls, 1)
        finished = [row for row in self.store.list_events(self.program)
                    if row["event_type"] == "BUILD_ATTEMPT_FINISHED" and row["payload"].get("attempt_id", "").startswith("AGENT-")][-1]
        payload = finished["payload"]
        self.assertEqual(payload["artifacts"]["PROOF"]["sha256"], __import__("hashlib").sha256(b"CAS_CONTROLLER_OK").hexdigest())
        self.assertIsNotNone(payload["cas_manifest"])
        target = cas / payload["artifacts"]["PROOF"]["sha256"][:2] / payload["artifacts"]["PROOF"]["sha256"]
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), "CAS_CONTROLLER_OK")

    def test_controller_checks_independent_verifier_hash_before_dispatch(self):
        import hashlib, json as _json
        code = self.verifier / "check.py"; expected = self.verifier / "expected.json"
        code.write_text("import json; print(json.dumps({'status':'PASS'}))\n")
        expected.write_text('{"ok": true}\n')
        plan = _json.loads(_json.dumps(self.plan))
        task = plan["workpacks"][0]
        task["verifier"] = {"verifier_id": "V1", "owner": "verifier-owner",
            "code_ref": "check.py", "code_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
            "expected_ref": "expected.json", "expected_sha256": hashlib.sha256(expected.read_bytes()).hexdigest(),
            "input_policy": "CAS_ONLY"}
        now = datetime.now(timezone.utc).isoformat()
        revision = len(self.store.list_events(self.program))
        prepared = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": self.scope, "plan": plan}}], expected_revision=revision,
            idempotency_key="verify-prepare", created_at=now, require_new=True)[0]
        self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED",
            "payload": {"prepared_event_id": prepared["event_id"]}}], expected_revision=revision + 1,
            idempotency_key="verify-approve", created_at=now, require_new=True)
        adapter = FlakyAdapter(self.workspace)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(prepared["event_id"])
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        finished = [row for row in self.store.list_events(self.program)
                    if row["event_type"] == "BUILD_ATTEMPT_FINISHED"][-1]["payload"]
        self.assertTrue(finished["verifier_identity"]["independent"])
        expected.write_text("tampered")
        revision = len(self.store.list_events(self.program))
        prepared2 = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": self.scope, "plan": plan}}], expected_revision=revision,
            idempotency_key="verify-prepare-2", created_at=now, require_new=True)[0]
        self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED",
            "payload": {"prepared_event_id": prepared2["event_id"]}}], expected_revision=revision + 1,
            idempotency_key="verify-approve-2", created_at=now, require_new=True)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: FlakyAdapter(self.workspace)).advance(prepared2["event_id"])
        self.assertEqual(result["status"], "HELD_VERIFIER_IDENTITY", result)

    def test_controller_requires_approval(self):
        other = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": self.scope, "plan": self.plan}}], expected_revision=2,
            idempotency_key="prepare-2", created_at=datetime.now(timezone.utc).isoformat(), require_new=True)[0]
        with self.assertRaises(ValueError):
            AgentBuildController(self.store, self.program).advance(other["event_id"])


if __name__ == "__main__":
    unittest.main()
