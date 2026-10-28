"""Experimental 1.3 controller dispatch through a fake DSH adapter."""

from __future__ import annotations

import json
import shutil
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness_foundry_factory.agents.agent_controller import AgentBuildController
from harness_foundry_factory.agents.scope13 import validate_scope_13
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
        (self.verifier / "check.py").write_text("print('ok')\n")
        self.dsh_home = self.root / "dsh-home"; self.dsh_home.mkdir()
        key_dir = self.dsh_home / "foundry"; key_dir.mkdir()
        self.key = key_dir / "deepseek.key"; self.key.write_text("fake-controller-key\n"); self.key.chmod(0o600)
        # The agent binary lives outside every task write root: an
        # implementation must not be able to rewrite the agent that drives it.
        bin_dir = self.root / "bin"; bin_dir.mkdir()
        self.dsh = bin_dir / "dsh"; shutil.copy2(FAKE, self.dsh)
        self.dsh.chmod(self.dsh.stat().st_mode | stat.S_IXUSR)
        self.plan = {
            "schema_version": "1.3", "plan_id": "P", "revision": 1, "requirement_revision": 1,
            "workpacks": [{
                "workpack_id": "IMPLEMENT", "job_id": "IMPLEMENT", "executor": "AGENT",
                "agent": {"adapter": "dsh-headless", "adapter_version": "1"},
                "goal": "Write proof.txt.", "depends_on": [], "atom_ids": ["A1"],
                "inputs": [], "artifacts": [{"artifact_id": "PROOF", "path": "proof.txt"}],
                "verification": [{"case_id": "C1", "argv": ["python", "verifier://check.py"], "artifact_ids": ["PROOF"]}],
            }],
        }
        # TRUSTED_HOST with an explicit "none" provider: platform-neutral, and the
        # scope says what actually runs (no sandbox) instead of displaying seatbelt.
        self.scope = {
            "scope_version": "1.3",
            "agents": {"dsh": {"adapter": "dsh-headless", "executable": str(self.dsh),
                               "dsh_home": str(self.dsh_home)}},
            "sandbox": {"provider": "none", "network": {"agent_egress": "NONE", "task_network": "NONE"}},
            "execution": {"mode": "TRUSTED_HOST"},
            "usage_accounting": "UNKNOWN", "workspace_root": str(self.workspace),
            "source_read_roots": [str(self.workspace)], "verification_root": str(self.verifier),
            "task_write_roots": {"IMPLEMENT": [str(self.workspace)]},
            "executables": {"python": sys.executable}, "max_attempts": 3, "max_task_attempts": 2,
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
        self.assertEqual(result["task_sandbox_provider"], "trusted-host")
        self.assertEqual(result["fs_enforcement"], "NONE")
        self.assertEqual(result["assurance"], "CONTRACT_INDEPENDENCE_DETECT_ONLY")
        finished = events[-1]["payload"]
        self.assertEqual((finished["fs_enforcement"], finished["execution_mode"]), ("NONE", "TRUSTED_HOST"))
        self.assertEqual(set(finished["checker_binding"]), {"check.py"})

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

    def _prepare(self, scope, plan, key):
        now = datetime.now(timezone.utc).isoformat()
        revision = len(self.store.list_events(self.program))
        prepared = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": scope, "plan": plan}}], expected_revision=revision,
            idempotency_key=key + "-prepare", created_at=now, require_new=True)[0]
        self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED",
            "payload": {"prepared_event_id": prepared["event_id"]}}], expected_revision=revision + 1,
            idempotency_key=key + "-approve", created_at=now, require_new=True)
        return prepared

    def _contract_plan(self):
        import hashlib
        code = self.verifier / "contract.py"; expected = self.verifier / "expected.json"
        code.write_text("import json; print(json.dumps({'status':'PASS'}))\n")
        expected.write_text('{"ok": true}\n')
        plan = json.loads(json.dumps(self.plan))
        plan["workpacks"][0]["verifier"] = {"verifier_id": "V1", "owner": "verifier-owner",
            "code_ref": "contract.py", "code_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
            "expected_ref": "expected.json", "expected_sha256": hashlib.sha256(expected.read_bytes()).hexdigest(),
            "input_policy": "CAS_ONLY"}
        return plan, expected

    def _cas_scope(self):
        staging = self.root / "staging"; staging.mkdir(exist_ok=True)
        cas = self.root / "cas"; cas.mkdir(exist_ok=True)
        scope = json.loads(json.dumps(self.scope))
        scope.update(staging_root=str(staging), cas_root=str(cas))
        return scope

    def test_controller_checks_independent_verifier_hash_before_dispatch(self):
        plan, expected = self._contract_plan()
        prepared = self._prepare(self._cas_scope(), plan, "verify")
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: StagingAdapter()).advance(prepared["event_id"])
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)
        finished = [row for row in self.store.list_events(self.program)
                    if row["event_type"] == "BUILD_ATTEMPT_FINISHED"][-1]["payload"]
        self.assertTrue(finished["verifier_identity"]["independent"])
        self.assertEqual(finished["verifier_result"]["status"], "PASS")
        expected.write_text("tampered")
        prepared2 = self._prepare(self._cas_scope(), plan, "verify-2")
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: StagingAdapter()).advance(prepared2["event_id"])
        self.assertEqual(result["status"], "HELD_VERIFIER_IDENTITY", result)

    def test_declared_verifier_contract_without_cas_is_held_not_skipped(self):
        plan, _ = self._contract_plan()
        prepared = self._prepare(self.scope, plan, "no-cas")
        adapter = FlakyAdapter(self.workspace)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(prepared["event_id"])
        self.assertEqual(result["status"], "HELD_VERIFIER_NOT_RUNNABLE", result)
        self.assertEqual(adapter.calls, 0)
        self.assertFalse(any(row["event_type"] == "BUILD_ATTEMPT_STARTED"
                             and row["payload"]["prepared_event_id"] == prepared["event_id"]
                             for row in self.store.list_events(self.program)))

    def test_checker_changed_since_preparation_is_held_before_dispatch(self):
        stale = {"check.py": {"size": 1, "sha256": "0" * 64}}
        now = datetime.now(timezone.utc).isoformat()
        revision = len(self.store.list_events(self.program))
        prepared = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": self.scope, "plan": self.plan, "verifier_files": stale}}],
            expected_revision=revision, idempotency_key="stale-prepare", created_at=now, require_new=True)[0]
        self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED",
            "payload": {"prepared_event_id": prepared["event_id"]}}], expected_revision=revision + 1,
            idempotency_key="stale-approve", created_at=now, require_new=True)
        adapter = FlakyAdapter(self.workspace)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(prepared["event_id"])
        self.assertEqual(result["status"], "HELD_VERIFIER_IDENTITY", result)
        self.assertEqual(adapter.calls, 0)

    def test_checker_rewritten_during_attempt_blocks_instead_of_accepting(self):
        class RewritingAdapter(FlakyAdapter):
            def run(inner, request, *, before_dispatch, **hooks):
                (self.verifier / "check.py").write_text("print('rewritten by the implementation')\n")
                return super().run(request, before_dispatch=before_dispatch, **hooks)

        adapter = RewritingAdapter(self.workspace, fail_first=False)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(self.prepared["event_id"])
        self.assertEqual(result["status"], "HELD_VERIFIER_IDENTITY", result)
        finished = [row for row in self.store.list_events(self.program)
                    if row["event_type"] == "BUILD_ATTEMPT_FINISHED"][-1]["payload"]
        self.assertEqual((finished["status"], finished["blocked_reason"]), ("BLOCKED", "VERIFIER_IDENTITY_DRIFT"))
        self.assertFalse(finished["workpack_accepted"])

    def test_scope_rejects_task_writable_binaries_and_mislabelled_sandbox(self):
        inside = self.workspace / "dsh"; shutil.copy2(FAKE, inside)
        inside.chmod(inside.stat().st_mode | stat.S_IXUSR)
        scope = json.loads(json.dumps(self.scope))
        scope["agents"]["dsh"]["executable"] = str(inside)
        with self.assertRaisesRegex(ValueError, "must not be task-writable"):
            validate_scope_13(self.plan, scope)
        scope = json.loads(json.dumps(self.scope))
        scope["executables"]["python"] = str(inside)
        with self.assertRaisesRegex(ValueError, "must not be task-writable"):
            validate_scope_13(self.plan, scope)
        # A seatbelt label on a TRUSTED_HOST run would be a claim the run cannot honour.
        scope = json.loads(json.dumps(self.scope))
        scope["sandbox"]["provider"] = "seatbelt"
        with self.assertRaisesRegex(ValueError, "TRUSTED_HOST execution runs unsandboxed"):
            validate_scope_13(self.plan, scope)
        # "none" without an explicit TRUSTED_HOST declaration stays test-only.
        scope = json.loads(json.dumps(self.scope))
        del scope["execution"]
        with self.assertRaisesRegex(ValueError, "needs explicit execution.mode TRUSTED_HOST"):
            validate_scope_13(self.plan, scope)
        validate_scope_13(self.plan, scope, test_only=True)

    def test_helper_added_to_verifier_root_after_binding_is_detected(self):
        """The binding covers the whole checker directory, not only referenced files."""
        from harness_foundry_factory.agents.scope13 import verifier_files
        bound = verifier_files(self.plan, self.scope)
        (self.verifier / "helpers.py").write_text("EXPECTED = 42\n")
        (self.verifier / "__pycache__").mkdir()
        (self.verifier / "__pycache__" / "check.cpython-312.pyc").write_bytes(b"\x00")
        changed = verifier_files(self.plan, self.scope)
        self.assertEqual(set(changed) - set(bound), {"helpers.py"})   # caches never count as a change
        now = datetime.now(timezone.utc).isoformat()
        revision = len(self.store.list_events(self.program))
        prepared = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": self.scope, "plan": self.plan, "verifier_files": bound}}],
            expected_revision=revision, idempotency_key="tree-prepare", created_at=now, require_new=True)[0]
        self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_APPROVED",
            "payload": {"prepared_event_id": prepared["event_id"]}}], expected_revision=revision + 1,
            idempotency_key="tree-approve", created_at=now, require_new=True)
        adapter = FlakyAdapter(self.workspace)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(prepared["event_id"])
        self.assertEqual(result["status"], "HELD_VERIFIER_IDENTITY", result)
        self.assertEqual(adapter.calls, 0)

    def test_owner_independence_is_recorded_not_enforced(self):
        plan, _ = self._contract_plan()                      # verifier owner: "verifier-owner"
        scope = self._cas_scope()
        scope["agents"]["dsh"]["owner"] = "verifier-owner"   # same party wrote producer config and checker
        prepared = self._prepare(scope, plan, "same-owner")
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: StagingAdapter()).advance(prepared["event_id"])
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED", result)   # labelled, still accepted
        self.assertEqual(result["owner_independence"], ["SAME_OWNER"])
        finished = [row for row in self.store.list_events(self.program)
                    if row["event_type"] == "BUILD_ATTEMPT_FINISHED"][-1]["payload"]
        self.assertEqual(finished["owner_independence"], "SAME_OWNER")
        scope["agents"]["dsh"]["owner"] = "producer-team"
        prepared = self._prepare(scope, plan, "distinct-owner")
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: StagingAdapter()).advance(prepared["event_id"])
        self.assertIn("DISTINCT", result["owner_independence"])
        del scope["agents"]["dsh"]["owner"]
        prepared = self._prepare(scope, plan, "undeclared-owner")
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: StagingAdapter()).advance(prepared["event_id"])
        self.assertIn("UNDECLARED", result["owner_independence"])

    def test_feedback_to_the_producer_carries_only_the_public_reason(self):
        (self.verifier / "check.py").write_text(
            "import json, sys\n"
            "print(json.dumps({'status': 'CHECKS_FAILED', 'failure_kind': 'ASSERTION',"
            " 'public_reason': 'proof.txt must name the artifact',"
            " 'private_detail': {'expected': 'SECRET-EXPECTED-VALUE'}}))\n"
            "sys.exit(1)\n")
        adapter = FlakyAdapter(self.workspace, fail_first=False)
        result = AgentBuildController(self.store, self.program,
                                      adapter_factory=lambda task, scope: adapter).advance(self.prepared["event_id"])
        self.assertEqual(result["status"], "TASK_REPAIR_BUDGET_EXHAUSTED", result)
        self.assertEqual(adapter.calls, 2)
        repair_prompt = adapter.prompts[1]
        self.assertIn("proof.txt must name the artifact", repair_prompt)
        self.assertNotIn("SECRET-EXPECTED-VALUE", repair_prompt)
        self.assertNotIn("private_detail", repair_prompt)
        repair = [row for row in self.store.list_events(self.program)
                  if row["event_type"] == "BUILD_AGENT_REPAIR_REQUESTED"][0]["payload"]
        self.assertNotIn("SECRET-EXPECTED-VALUE", repair["feedback"])

    def test_scope_requires_verifier_files_or_a_verifier_contract(self):
        plan = json.loads(json.dumps(self.plan))
        plan["workpacks"][0]["verification"] = [{"case_id": "C1", "argv": ["python", "-c", "pass"], "artifact_ids": ["PROOF"]}]
        with self.assertRaisesRegex(ValueError, "verifier:// files or declare a verifier contract"):
            validate_scope_13(self.plan | {"workpacks": plan["workpacks"]}, self.scope)
        plan["workpacks"][0]["verifier"] = {"verifier_id": "V1", "owner": "o", "code_ref": "c.py",
            "code_sha256": "0" * 64, "expected_ref": "e.json", "expected_sha256": "0" * 64}
        validate_scope_13(plan, self.scope)
        plan = json.loads(json.dumps(self.plan))
        plan["workpacks"][0]["verification"][0]["argv"] = ["python", "verifier://missing.py"]
        with self.assertRaisesRegex(ValueError, "verifier file is missing"):
            validate_scope_13(plan, self.scope)

    def test_controller_requires_approval(self):
        other = self.store.append_batch(self.program, [{"event_type": "BUILD_AUTHORIZATION_PREPARED",
            "payload": {"scope": self.scope, "plan": self.plan}}], expected_revision=2,
            idempotency_key="prepare-2", created_at=datetime.now(timezone.utc).isoformat(), require_new=True)[0]
        with self.assertRaises(ValueError):
            AgentBuildController(self.store, self.program).advance(other["event_id"])


if __name__ == "__main__":
    unittest.main()
