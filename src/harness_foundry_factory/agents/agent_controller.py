"""Experimental Plan/Scope 1.3 controller path.

This is deliberately separate from the mature Codex/local controller: it
requires a prepared event that carries the 1.3 plan/scope and dispatches
through agent adapters. Its attempt, acceptance and budget facts come from the
same projections (`build_state`) and the same elided stream reads as the 1.2
controller and `read-build`, so budgets are cumulative across calls and
invalidations are honoured.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from .base import AgentRequest
from .dsh import DshHeadlessAdapter
from .api import DeepseekApiAdapter
from .sandbox_none import NoneSandboxProvider
from .sandbox_seatbelt import SeatbeltSandboxProvider
from .sandbox_bwrap import BubblewrapSandboxProvider
from .sandbox_trusted import TrustedHostProvider
from .scope13 import (agent_read_roots, assurance_label, execution_mode, fs_enforcement,
                      owner_independence, validate_scope_13, verifier_files)
from .artifacts import ingest as ingest_artifacts
from harness_foundry_factory.build_check_protocol import public_feedback
from harness_foundry_factory.build_state import attempt_budget, project_budget_attempts, project_execution_state
from .verifier import VerifierContract, VerifierContractError
from .verifier_runner import run_verifier


def _event(events, event_id, kind):
    for event in events:
        if event["event_id"] == event_id and event["event_type"] == kind:
            return event
    raise ValueError(f"missing {kind}: {event_id}")


class AgentBuildController:
    def __init__(self, store, program_id, *, adapter_factory=None, provider=None):
        self.store = store
        self.program_id = program_id
        self.adapter_factory = adapter_factory
        self.provider = provider

    def _default_adapter(self, task, scope):
        definition = next((row for row in scope["agents"].values()
                           if row.get("adapter") == task["agent"]["adapter"]), None)
        if definition is None:
            raise ValueError("no agent definition for task adapter")
        if definition["adapter"] == "dsh-headless":
            return DshHeadlessAdapter(definition["executable"], definition.get("dsh_home", Path.home() / ".dsh"),
                                      key_file=definition.get("key_file"))
        if definition["adapter"] == "deepseek-api":
            model = definition.get("model", {}).get("name", "deepseek-chat")
            insecure_hosts = ("host.lima.internal",) if "host.lima.internal" in definition["base_url"] else ()
            return DeepseekApiAdapter(base_url=definition["base_url"], model=model,
                                      key_file=definition.get("key_file"), provider=self.provider,
                                      allow_insecure_localhost=definition["base_url"].startswith("http://127.0.0.1"),
                                      allow_insecure_hosts=insecure_hosts)
        raise ValueError(f"unsupported agent adapter: {definition['adapter']}")

    @staticmethod
    def _prompt(task, feedback=None):
        artifacts = ", ".join(item["path"] for item in task["artifacts"])
        prompt = (f"Implement workpack {task['workpack_id']} in the current workspace. "
                  f"Goal: {task['goal']}. Write only declared artifacts: {artifacts}. "
                  "Do not claim acceptance. Use the provided tools and finish with a short report.")
        if feedback:
            prompt += "\nPrevious attempt was rejected; fix the observed failure rather than repeating it.\n" + feedback
        return prompt

    def _provider(self, scope):
        """The provider the validated scope declares; never a silent platform guess."""
        if self.provider is not None:
            return self.provider
        if execution_mode(scope) == "TRUSTED_HOST":
            return TrustedHostProvider()
        provider = scope["sandbox"]["provider"]
        if provider == "seatbelt":
            return SeatbeltSandboxProvider()
        if provider == "bwrap":
            return BubblewrapSandboxProvider()
        return NoneSandboxProvider(allow_unsandboxed_agent=True)

    @staticmethod
    def _enforcement(scope, provider):
        """Facts about what actually constrained the task process, from the
        provider that ran it rather than from the scope's declaration."""
        provider_id = getattr(provider, "provider_id", "UNKNOWN")
        sandboxed = provider_id in {"seatbelt", "bwrap"}
        return {"execution_mode": execution_mode(scope),
                "fs_enforcement": "SANDBOX" if sandboxed else "NONE",
                "assurance": "CONTRACT_PLUS_SANDBOX" if sandboxed else "CONTRACT_INDEPENDENCE_DETECT_ONLY",
                "declared_fs_enforcement": fs_enforcement(scope),
                "declared_assurance": assurance_label(scope),
                "task_sandbox_provider": provider_id}

    def _verify(self, task, scope, workspace):
        results = []
        for check in task["verification"]:
            argv = list(check["argv"])
            executable = scope["executables"].get(argv[0])
            if executable is None and not Path(argv[0]).is_absolute():
                raise ValueError(f"verification executable is not declared: {argv[0]}")
            argv[0] = executable or argv[0]
            for index, value in enumerate(argv):
                if value.startswith("verifier://"):
                    argv[index] = str((Path(scope["verification_root"]) / value.removeprefix("verifier://")).resolve())
            command = SimpleNamespace(argv=argv, cwd=workspace,
                                      read_roots=[workspace, Path(scope["verification_root"]), *agent_read_roots(scope)],
                                      write_roots=[], timeout_seconds=scope["command_timeout_seconds"],
                                      environment={}, network=None)
            observed = self._provider(scope).run(command, before_dispatch=lambda: None)
            results.append({"case_id": check["case_id"], "result": {key: observed.get(key) for key in
                            ("status", "provider_id", "exit_code", "stdout", "stderr")}})
            if observed.get("status") != "PASS":
                break
        return results

    def _events(self):
        """The complete stream with source bodies elided (shared with the 1.2 controller)."""
        from harness_foundry_factory.build_runtime import control_events
        return control_events(self.store, self.program_id)

    @staticmethod
    def _budget(events, prepared_id, scope):
        """Cumulative budget over the whole lineage, the same projection the 1.2
        controller and read-build use; a fresh advance() call does not reset it."""
        return attempt_budget(scope, list(project_budget_attempts(events, prepared_id).values()))

    def advance(self, prepared_id):
        events = self._events()
        prepared = _event(events, prepared_id, "BUILD_AUTHORIZATION_PREPARED")
        scope = prepared["payload"]["scope"]
        plan = prepared["payload"].get("plan")
        if not isinstance(plan, dict) or plan.get("schema_version") != "1.3":
            raise ValueError("AgentBuildController requires a prepared 1.3 plan")
        if not any(row["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                   and row["payload"].get("prepared_event_id") == prepared_id for row in events):
            raise ValueError("agent build authorization is not approved")
        if any(row["event_type"] == "BUILD_AUTHORIZATION_REVOKED"
               and row["payload"].get("prepared_event_id") == prepared_id for row in events):
            raise ValueError("agent build authorization is revoked")
        validate_scope_13(plan, scope)
        # Recover only from persisted old events; never re-dispatch an uncertain
        # attempt or a task the store already accepted. Both facts come from the
        # shared projection, so invalidation events are honoured here too.
        task_ids = {task["workpack_id"] for task in plan["workpacks"]}
        attempts, accepted_records = project_execution_state(events, prepared_id)
        unresolved = sorted(key for key, row in attempts.items()
                            if row["status"] in {"IN_FLIGHT", "UNKNOWN_SIDE_EFFECT"})
        if unresolved:
            return {"status": "HELD_UNRESOLVED_ATTEMPT", "attempt_ids": unresolved,
                    "accepted_workpacks": [],
                    "next_action": "RECONCILE_EFFECTS", "execution_started": False,
                    "harness_e2e_verified": False}
        agent_sandbox = "UNKNOWN"
        finished = {key: {"payload": row} for key, row in accepted_records.items() if key in task_ids}
        accepted = sorted(finished)
        workspace = Path(scope["workspace_root"]).resolve()
        staging_root = Path(scope["staging_root"]).resolve() if "staging_root" in scope else None
        cas_root = Path(scope["cas_root"]).resolve() if "cas_root" in scope else None
        use_cas = staging_root is not None and cas_root is not None
        provider = self._provider(scope)
        enforcement = self._enforcement(scope, provider)
        # verifier:// files are bound at preparation (when prepared through the
        # host) and re-read here; any drift stops before dispatch.
        try:
            checker_binding = verifier_files(plan, scope)
        except (OSError, ValueError) as exc:
            return {"status": "HELD_VERIFIER_IDENTITY", "diagnostic": str(exc),
                    "execution_started": False, "harness_e2e_verified": False}
        prepared_binding = prepared["payload"].get("verifier_files") or None
        if prepared_binding is not None and prepared_binding != checker_binding:
            return {"status": "HELD_VERIFIER_IDENTITY",
                    "diagnostic": "verification files changed since preparation",
                    "execution_started": False, "harness_e2e_verified": False}
        if use_cas:
            staging_root.mkdir(parents=True, exist_ok=True)
            cas_root.mkdir(parents=True, exist_ok=True)
        for row in finished.values():
            if row["payload"].get("status") != "ACCEPTED":
                continue
            for artifact in row["payload"].get("artifacts", {}).values():
                path = (workspace / artifact.get("path", "")).resolve()
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256"):
                    return {"status": "HELD_ACCEPTED_ARTIFACT_DRIFT", "workpack_id": row["payload"].get("workpack_id"),
                            "artifact": artifact.get("path"), "execution_started": False,
                            "next_action": "EXPLICIT_REBUILD_PLAN", "harness_e2e_verified": False}
        ownership_labels = {row["payload"]["owner_independence"] for row in finished.values()
                            if "owner_independence" in row["payload"]}
        for task in plan["workpacks"]:
            if task["workpack_id"] in accepted:
                continue
            if task.get("executor") != "AGENT":
                raise ValueError("experimental controller only dispatches AGENT workpacks")
            adapter = (self.adapter_factory(task, scope) if self.adapter_factory
                       else self._default_adapter(task, scope))
            agent_sandbox = getattr(getattr(adapter, "capabilities", None), "sandbox", "UNKNOWN")
            verifier_identity = None
            verifier_contract = None
            if "verifier" in task:
                try:
                    verifier_contract = VerifierContract.from_dict(task["verifier"])
                    verifier_identity = verifier_contract.verify_files(
                        Path(scope["verification_root"]) / verifier_contract.code_ref,
                        Path(scope["verification_root"]) / verifier_contract.expected_ref)
                except (OSError, ValueError, VerifierContractError) as exc:
                    return {"status": "HELD_VERIFIER_IDENTITY", "workpack_id": task["workpack_id"],
                            "diagnostic": str(exc), "execution_started": False,
                            "harness_e2e_verified": False}
                if not use_cas:
                    # A declared independent verifier that cannot run must not
                    # silently degrade acceptance to the plain checks.
                    return {"status": "HELD_VERIFIER_NOT_RUNNABLE", "workpack_id": task["workpack_id"],
                            "diagnostic": "verifier contract requires staging_root and cas_root (CAS_ONLY inputs)",
                            "next_action": "CONFIGURE_STAGING_AND_CAS", "execution_started": False,
                            "harness_e2e_verified": False}
            # Recorded, not enforced: the system cannot know who wrote either side.
            ownership = {"owner_independence": owner_independence(
                scope, task, verifier_contract.owner if verifier_contract is not None else None)}
            ownership_labels.add(ownership["owner_independence"])
            owners = prepared["payload"].get("task_budget_owners", {}).get(task["workpack_id"], [task["workpack_id"]])
            feedback = None
            while True:
                budget = self._budget(events, prepared_id, scope)
                used = budget["attempts_consumed"]
                if budget["attempts_remaining"] <= 0:
                    return {"status": "ATTEMPT_BUDGET_EXHAUSTED", "accepted_workpacks": accepted,
                            "attempts_used": used, "budget": budget, "execution_started": True,
                            "harness_e2e_verified": False}
                if any(budget["task_attempts_remaining"].get(owner, scope["max_task_attempts"]) <= 0 for owner in owners):
                    return {"status": "TASK_REPAIR_BUDGET_EXHAUSTED", "workpack_id": task["workpack_id"],
                            "accepted_workpacks": accepted, "attempts_used": used, "budget": budget,
                            "execution_started": True, "harness_e2e_verified": False}
                attempt_id = "AGENT-ATTEMPT-" + uuid4().hex
                started = {"attempt_id": attempt_id, "workpack_id": task["workpack_id"],
                           "job_id": task["job_id"], "prepared_event_id": prepared_id,
                           "proposal_event_id": prepared["payload"].get("proposal_event_id"),
                           "budget_workpack_ids": owners, "executor": "AGENT",
                           "adapter": task["agent"]["adapter"],
                           "checker_binding": checker_binding, **enforcement, **ownership,
                       **({"verifier_identity": verifier_identity} if verifier_identity is not None else {})}
                self.store.append_batch(self.program_id, [{"event_type": "BUILD_ATTEMPT_STARTED",
                    "payload": started}], expected_revision=len(events),
                    idempotency_key=attempt_id + ":start",
                    created_at=datetime.now(timezone.utc).isoformat(), require_new=True)
                events = self._events()
                attempt_workspace = (staging_root / attempt_id) if use_cas else workspace
                if use_cas:
                    attempt_workspace.mkdir(parents=True, exist_ok=True)
                command = SimpleNamespace(scope=SimpleNamespace(
                    cwd=attempt_workspace,
                    read_roots=(attempt_workspace, *[Path(root) for root in scope["source_read_roots"]],
                                *agent_read_roots(scope)),
                    write_roots=(attempt_workspace,),
                    timeout_seconds=scope["command_timeout_seconds"], environment={},
                    max_cpu_seconds=scope.get("max_cpu_seconds"), max_memory_bytes=scope.get("max_memory_bytes"),
                    max_fds=scope.get("max_fds"), max_output_bytes=scope.get("max_output_bytes")))
                result = adapter.run(AgentRequest(command=command, prompt=self._prompt(task, feedback)),
                                     before_dispatch=lambda: None)
                artifacts = {}
                artifact_error = None
                cas_manifest = None
                verification_root = attempt_workspace
                try:
                    if use_cas:
                        cas = ingest_artifacts(attempt_workspace, cas_root, task["artifacts"], attempt_id=attempt_id)
                        cas_manifest = cas["manifest"]
                        artifacts = {row["artifact_id"]: {"path": row["path"], "size": row["size"],
                                                          "sha256": row["sha256"], "cas_ref": row["cas_ref"]}
                                     for row in cas_manifest["entries"]}
                        verification_root = Path(tempfile.mkdtemp(prefix="foundry-cas-view-"))
                        for row in cas_manifest["entries"]:
                            source = cas_root / row["sha256"][:2] / row["sha256"]
                            target = verification_root / row["path"]
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(source, target)
                            target.chmod(0o444)
                    else:
                        for item in task["artifacts"]:
                            path = (workspace / item["path"]).resolve()
                            if not path.is_file():
                                raise ValueError(f"declared artifact missing: {item['path']}")
                            artifacts[item["artifact_id"]] = {
                                "path": item["path"], "size": path.stat().st_size,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                except (OSError, ValueError) as exc:
                    artifact_error = str(exc)
                verifier_drift = None
                if artifact_error is None:
                    try:
                        current_binding = verifier_files(plan, scope)
                    except (OSError, ValueError) as exc:
                        current_binding, verifier_drift = None, str(exc)
                    if verifier_drift is None and current_binding != checker_binding:
                        verifier_drift = "verification files changed during the attempt"
                verification = [] if artifact_error or verifier_drift else self._verify(task, scope, verification_root)
                verifier_result = None
                if verifier_contract is not None and use_cas and artifact_error is None:
                    try:
                        verifier_result = run_verifier(
                            verifier_contract, verifier_root=scope["verification_root"], cas_root=cas_root,
                            case_id=task["workpack_id"], provider=self._provider(scope))
                    except (OSError, ValueError) as exc:
                        verifier_result = {"status": "BLOCKED", "reason_code": "VERIFIER_RUN_FAILED",
                                           "diagnostic": str(exc), "acceptance": False}
                if use_cas:
                    shutil.rmtree(verification_root, ignore_errors=True)
                passed = (result.get("status") == "PASS" and artifact_error is None and verifier_drift is None
                          and bool(verification) and all(row["result"].get("status") == "PASS" for row in verification)
                          and (verifier_result is None or verifier_result.get("status") == "PASS"))
                # Checker drift is an infrastructure hold, not a product rejection.
                status = "ACCEPTED" if passed else "BLOCKED" if verifier_drift else "REJECTED"
                payload = {**started, "status": status,
                           "artifacts": artifacts, "artifact_error": artifact_error,
                           "verification": verification,
                           "effects": {"status": "NOT_OBSERVED", "external_effects_verified": False},
                           "result": result, "workpack_accepted": passed, "cas_manifest": cas_manifest,
                           **({"verifier_identity": verifier_identity} if verifier_identity is not None else {}),
                           **({"verifier_result": verifier_result} if verifier_result is not None else {}),
                           **({"blocked_reason": "VERIFIER_IDENTITY_DRIFT", "diagnostic": verifier_drift}
                              if verifier_drift else {}),
                           "agent_sandbox_enforcement": getattr(getattr(adapter, "capabilities", None), "sandbox", "UNKNOWN"),
                           **enforcement}
                self.store.append_batch(self.program_id, [{"event_type": "BUILD_ATTEMPT_FINISHED",
                    "payload": payload}], expected_revision=len(events),
                    idempotency_key=attempt_id + ":finish",
                    created_at=datetime.now(timezone.utc).isoformat(), require_new=True)
                events = self._events()
                if passed:
                    accepted.append(task["workpack_id"])
                    break
                budget = self._budget(events, prepared_id, scope)
                used = budget["attempts_consumed"]
                if verifier_drift:
                    return {"status": "HELD_VERIFIER_IDENTITY", "workpack_id": task["workpack_id"],
                            "attempt_id": attempt_id, "diagnostic": verifier_drift,
                            "accepted_workpacks": accepted, "attempts_used": used, "budget": budget,
                            "execution_started": True, "harness_e2e_verified": False}
                task_exhausted = any(budget["task_attempts_remaining"].get(owner, scope["max_task_attempts"]) <= 0
                                     for owner in owners)
                if task_exhausted:
                    return {"status": "TASK_REPAIR_BUDGET_EXHAUSTED", "workpack_id": task["workpack_id"],
                            "attempt_id": attempt_id, "artifact_error": artifact_error,
                            "verification": verification, "accepted_workpacks": accepted,
                            "attempts_used": used, "budget": budget, "execution_started": True,
                            "harness_e2e_verified": False}
                # Checkers that separate public_reason from private_detail
                # feed only the public part back to the producer.
                projected = [{**row, "result": public_feedback(row["result"]) or row["result"]} for row in verification]
                feedback = str({"artifact_error": artifact_error, "verification": projected})[:2000]
                if budget["attempts_remaining"] > 0:
                    self.store.append_batch(self.program_id, [{
                        "event_type": "BUILD_AGENT_REPAIR_REQUESTED",
                        "payload": {"prepared_event_id": prepared_id, "workpack_id": task["workpack_id"],
                                    "failed_attempt_id": attempt_id, "feedback": feedback,
                                    "budget_workpack_ids": owners}}],
                        expected_revision=len(events), idempotency_key=attempt_id + ":repair",
                        created_at=datetime.now(timezone.utc).isoformat(), require_new=True)
                    events = self._events()
                else:
                    return {"status": "ATTEMPT_BUDGET_EXHAUSTED", "workpack_id": task["workpack_id"],
                            "attempt_id": attempt_id, "artifact_error": artifact_error,
                            "verification": verification, "accepted_workpacks": accepted,
                            "attempts_used": used, "budget": budget, "execution_started": True,
                            "harness_e2e_verified": False}
        budget = self._budget(events, prepared_id, scope)
        return {"status": "PLAN_CHECKS_ACCEPTED", "accepted_workpacks": accepted,
                "attempts_used": budget["attempts_consumed"], "budget": budget, "agent_controller": "EXPERIMENTAL_1_3",
                "agent_sandbox_enforcement": agent_sandbox, **enforcement,
                "owner_independence": sorted(ownership_labels) or ["UNDECLARED"],
                "harness_e2e_verified": False}
