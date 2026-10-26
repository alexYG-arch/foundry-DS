"""Experimental Plan/Scope 1.3 controller path.

This is deliberately separate from the mature Codex/local controller. It
requires a prepared event that carries the 1.3 plan/scope, and it records its
own attempt events. It is a fixture/transition path, not a replacement for the
existing acceptance projection until that projection is extended.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from .base import AgentRequest
from .dsh import DshHeadlessAdapter
from .api import DeepseekApiAdapter
from .sandbox_seatbelt import SeatbeltSandboxProvider
from .sandbox_bwrap import BubblewrapSandboxProvider
from .scope13 import validate_scope_13


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
        self.provider = provider or (SeatbeltSandboxProvider()
                                      if Path("/usr/bin/sandbox-exec").is_file()
                                      else BubblewrapSandboxProvider())

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
                                      read_roots=[workspace, Path(scope["verification_root"])],
                                      write_roots=[], timeout_seconds=scope["command_timeout_seconds"],
                                      environment={}, network=None)
            observed = self.provider.run(command, before_dispatch=lambda: None)
            results.append({"case_id": check["case_id"], "result": {key: observed.get(key) for key in
                            ("status", "provider_id", "exit_code", "stdout", "stderr")}})
            if observed.get("status") != "PASS":
                break
        return results

    def advance(self, prepared_id):
        events = self.store.list_events(self.program_id)
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
        # attempt or a task the store already accepted.
        task_ids = {task["workpack_id"] for task in plan["workpacks"]}
        started = {row["payload"].get("attempt_id") for row in events
                   if row["event_type"] == "BUILD_ATTEMPT_STARTED"
                   and row["payload"].get("prepared_event_id") == prepared_id}
        finished = {row["payload"].get("attempt_id"): row for row in events
                    if row["event_type"] == "BUILD_ATTEMPT_FINISHED"
                    and row["payload"].get("prepared_event_id") == prepared_id}
        unresolved = sorted(key for key in started - set(finished) if key)
        if unresolved:
            return {"status": "HELD_UNRESOLVED_ATTEMPT", "attempt_ids": unresolved,
                    "accepted_workpacks": [],
                    "next_action": "RECONCILE_EFFECTS", "execution_started": False,
                    "harness_e2e_verified": False}
        agent_sandbox = "UNKNOWN"
        accepted = sorted({row["payload"]["workpack_id"] for row in finished.values()
                           if row["payload"].get("status") == "ACCEPTED"
                           and row["payload"].get("workpack_id") in task_ids})
        workspace = Path(scope["workspace_root"]).resolve()
        for row in finished.values():
            if row["payload"].get("status") != "ACCEPTED":
                continue
            for artifact in row["payload"].get("artifacts", {}).values():
                path = (workspace / artifact.get("path", "")).resolve()
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256"):
                    return {"status": "HELD_ACCEPTED_ARTIFACT_DRIFT", "workpack_id": row["payload"].get("workpack_id"),
                            "artifact": artifact.get("path"), "execution_started": False,
                            "next_action": "EXPLICIT_REBUILD_PLAN", "harness_e2e_verified": False}
        used = 0
        for task in plan["workpacks"]:
            if task["workpack_id"] in accepted:
                continue
            if task.get("executor") != "AGENT":
                raise ValueError("experimental controller only dispatches AGENT workpacks")
            adapter = (self.adapter_factory(task, scope) if self.adapter_factory
                       else self._default_adapter(task, scope))
            agent_sandbox = getattr(getattr(adapter, "capabilities", None), "sandbox", "UNKNOWN")
            task_attempts = 0
            feedback = None
            while True:
                if used >= scope["max_attempts"]:
                    return {"status": "ATTEMPT_BUDGET_EXHAUSTED", "accepted_workpacks": accepted,
                            "attempts_used": used, "execution_started": True,
                            "harness_e2e_verified": False}
                if task_attempts >= scope["max_task_attempts"]:
                    return {"status": "TASK_REPAIR_BUDGET_EXHAUSTED", "workpack_id": task["workpack_id"],
                            "accepted_workpacks": accepted, "attempts_used": used,
                            "execution_started": True, "harness_e2e_verified": False}
                used += 1
                task_attempts += 1
                attempt_id = "AGENT-ATTEMPT-" + uuid4().hex
                owners = prepared.get("task_budget_owners", {}).get(task["workpack_id"], [task["workpack_id"]])
                started = {"attempt_id": attempt_id, "workpack_id": task["workpack_id"],
                           "job_id": task["job_id"], "prepared_event_id": prepared_id,
                           "proposal_event_id": prepared.get("proposal_event_id"),
                           "budget_workpack_ids": owners, "executor": "AGENT",
                           "adapter": task["agent"]["adapter"]}
                self.store.append_batch(self.program_id, [{"event_type": "BUILD_ATTEMPT_STARTED",
                    "payload": started}], expected_revision=len(events),
                    idempotency_key=attempt_id + ":start",
                    created_at=datetime.now(timezone.utc).isoformat(), require_new=True)
                events = self.store.list_events(self.program_id)
                command = SimpleNamespace(scope=SimpleNamespace(
                    cwd=workspace, read_roots=(workspace, *[Path(root) for root in scope["source_read_roots"]]),
                    write_roots=tuple(Path(root) for root in scope["task_write_roots"][task["workpack_id"]]),
                    timeout_seconds=scope["command_timeout_seconds"], environment={}))
                result = adapter.run(AgentRequest(command=command, prompt=self._prompt(task, feedback)),
                                     before_dispatch=lambda: None)
                artifacts = {}
                artifact_error = None
                try:
                    for item in task["artifacts"]:
                        path = (workspace / item["path"]).resolve()
                        if not path.is_file():
                            raise ValueError(f"declared artifact missing: {item['path']}")
                        artifacts[item["artifact_id"]] = {
                            "path": item["path"], "size": path.stat().st_size,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                except (OSError, ValueError) as exc:
                    artifact_error = str(exc)
                verification = [] if artifact_error else self._verify(task, scope, workspace)
                passed = (result.get("status") == "PASS" and artifact_error is None
                          and bool(verification) and all(row["result"].get("status") == "PASS" for row in verification))
                payload = {**started, "status": "ACCEPTED" if passed else "REJECTED",
                           "artifacts": artifacts, "artifact_error": artifact_error,
                           "verification": verification,
                           "effects": {"status": "NOT_OBSERVED", "external_effects_verified": False},
                           "result": result, "workpack_accepted": passed,
                           "agent_sandbox_enforcement": getattr(getattr(adapter, "capabilities", None), "sandbox", "UNKNOWN"),
                           "task_sandbox_provider": getattr(self.provider, "provider_id", "UNKNOWN")}
                self.store.append_batch(self.program_id, [{"event_type": "BUILD_ATTEMPT_FINISHED",
                    "payload": payload}], expected_revision=len(events),
                    idempotency_key=attempt_id + ":finish",
                    created_at=datetime.now(timezone.utc).isoformat(), require_new=True)
                events = self.store.list_events(self.program_id)
                if passed:
                    accepted.append(task["workpack_id"])
                    break
                if task_attempts >= scope["max_task_attempts"]:
                    return {"status": "TASK_REPAIR_BUDGET_EXHAUSTED", "workpack_id": task["workpack_id"],
                            "attempt_id": attempt_id, "artifact_error": artifact_error,
                            "verification": verification, "accepted_workpacks": accepted,
                            "attempts_used": used, "execution_started": True,
                            "harness_e2e_verified": False}
                feedback = str({"artifact_error": artifact_error,
                                "verification": verification})[:2000]
                if task_attempts < scope["max_task_attempts"] and used < scope["max_attempts"]:
                    self.store.append_batch(self.program_id, [{
                        "event_type": "BUILD_AGENT_REPAIR_REQUESTED",
                        "payload": {"prepared_event_id": prepared_id, "workpack_id": task["workpack_id"],
                                    "failed_attempt_id": attempt_id, "feedback": feedback,
                                    "budget_workpack_ids": owners}}],
                        expected_revision=len(events), idempotency_key=attempt_id + ":repair",
                        created_at=datetime.now(timezone.utc).isoformat(), require_new=True)
                    events = self.store.list_events(self.program_id)
                if used >= scope["max_attempts"]:
                    return {"status": "ATTEMPT_BUDGET_EXHAUSTED", "workpack_id": task["workpack_id"],
                            "attempt_id": attempt_id, "artifact_error": artifact_error,
                            "verification": verification, "accepted_workpacks": accepted,
                            "attempts_used": used, "execution_started": True,
                            "harness_e2e_verified": False}
        return {"status": "PLAN_CHECKS_ACCEPTED", "accepted_workpacks": accepted,
                "attempts_used": used, "agent_controller": "EXPERIMENTAL_1_3",
                "agent_sandbox_enforcement": agent_sandbox,
                "task_sandbox_provider": getattr(self.provider, "provider_id", "UNKNOWN"),
                "harness_e2e_verified": False}
