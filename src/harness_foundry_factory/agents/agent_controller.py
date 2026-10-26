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
from .sandbox_seatbelt import SeatbeltSandboxProvider
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
        self.provider = provider or SeatbeltSandboxProvider()

    def _default_adapter(self, task, scope):
        definition = next((row for row in scope["agents"].values()
                           if row.get("adapter") == task["agent"]["adapter"]), None)
        if definition is None:
            raise ValueError("no agent definition for task adapter")
        if definition["adapter"] == "dsh-headless":
            return DshHeadlessAdapter(definition["executable"], definition.get("dsh_home", Path.home() / ".dsh"),
                                      key_file=definition.get("key_file"))
        raise ValueError(f"unsupported agent adapter: {definition['adapter']}")

    @staticmethod
    def _prompt(task):
        artifacts = ", ".join(item["path"] for item in task["artifacts"])
        return (f"Implement workpack {task['workpack_id']} in the current workspace. "
                f"Goal: {task['goal']}. Write only declared artifacts: {artifacts}. "
                "Do not claim acceptance. Use the provided tools and finish with a short report.")

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
        workspace = Path(scope["workspace_root"]).resolve()
        accepted = []
        used = 0
        for task in plan["workpacks"]:
            if task.get("executor") != "AGENT":
                raise ValueError("experimental controller only dispatches AGENT workpacks")
            adapter = (self.adapter_factory(task, scope) if self.adapter_factory
                       else self._default_adapter(task, scope))
            task_attempts = 0
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
                result = adapter.run(AgentRequest(command=command, prompt=self._prompt(task)),
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
                           "result": result, "workpack_accepted": passed}
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
                if used >= scope["max_attempts"]:
                    return {"status": "ATTEMPT_BUDGET_EXHAUSTED", "workpack_id": task["workpack_id"],
                            "attempt_id": attempt_id, "artifact_error": artifact_error,
                            "verification": verification, "accepted_workpacks": accepted,
                            "attempts_used": used, "execution_started": True,
                            "harness_e2e_verified": False}
        return {"status": "PLAN_CHECKS_ACCEPTED", "accepted_workpacks": accepted,
                "attempts_used": used, "agent_controller": "EXPERIMENTAL_1_3",
                "harness_e2e_verified": False}
