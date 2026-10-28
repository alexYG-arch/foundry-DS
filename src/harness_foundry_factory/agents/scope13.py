"""Scope 1.3 validation and AGENT dispatch (P1 fixture path).

The scope shape is deliberately separate from the 1.2 Codex scope: it has no
`codex_executable`, declares an adapter and a real sandbox provider, and fails
closed when the plan is not 1.3.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from .base import AgentRequest

SCOPE_FIELDS = {
    "scope_version", "agents", "sandbox", "usage_accounting", "workspace_root",
    "source_read_roots", "verification_root", "task_write_roots", "executables",
    "max_attempts", "max_task_attempts", "command_timeout_seconds", "expires_at",
}
OPTIONAL_FIELDS = {"staging_root", "cas_root", "execution", "max_cpu_seconds",
                    "max_memory_bytes", "max_fds", "max_output_bytes"}
AGENT_FIELDS = {"adapter", "executable", "dsh_home", "session", "model", "base_url", "key_file"}
SANDBOX_FIELDS = {"provider", "network"}
PROVIDERS = {"seatbelt", "bwrap", "none"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _absolute_file(value, label):
    _require(isinstance(value, str) and Path(value).is_absolute(), f"{label} must be an absolute path")
    path = Path(value)
    _require(path.is_file(), f"{label} must resolve to a file")
    return path


def _relative_under(root: Path, value, label):
    _require(isinstance(value, str) and value and ".." not in Path(value).parts,
             f"{label} must be a safe relative path")
    path = (root / value).resolve()
    _require(path.is_relative_to(root.resolve()), f"{label} escapes its root")
    return path


def validate_scope_13(plan, scope, *, test_only=False):
    """Validate a Scope 1.3 without requiring a Codex binary.

    `test_only` is only for explicit fixture tests using the `none` provider.
    Production callers must leave it false.
    """
    _require(isinstance(plan, dict) and plan.get("schema_version") == "1.3",
             "agent scope requires plan 1.3")
    _require(isinstance(scope, dict) and SCOPE_FIELDS <= set(scope) <= SCOPE_FIELDS | OPTIONAL_FIELDS,
             "scope 1.3 has missing or unsupported fields")
    _require(scope["scope_version"] == "1.3", "scope_version must be 1.3")
    _require("codex_executable" not in scope, "scope 1.3 must not require codex_executable")
    for name in ("staging_root", "cas_root"):
        if name in scope:
            _require(isinstance(scope[name], str) and Path(scope[name]).is_absolute(),
                     f"{name} must be an absolute path")
    for name in ("max_cpu_seconds", "max_memory_bytes", "max_fds", "max_output_bytes"):
        if name in scope:
            _require(isinstance(scope[name], int) and not isinstance(scope[name], bool) and scope[name] >= 0,
                     f"{name} must be a nonnegative integer")
    if "execution" in scope:
        execution = scope["execution"]
        _require(isinstance(execution, dict) and execution.get("mode") in
                 {"TRUSTED_HOST", "UID", "VM", "SANDBOX"},
                 "execution.mode is unsupported")
    if "staging_root" in scope and "cas_root" in scope:
        staging, cas = Path(scope["staging_root"]).resolve(), Path(scope["cas_root"]).resolve()
        _require(not staging.is_relative_to(cas) and not cas.is_relative_to(staging),
                 "staging and CAS must not contain each other")
    workspace = Path(scope["workspace_root"])
    _require(workspace.is_absolute() and workspace.is_dir(), "workspace_root must be an existing directory")
    verifier = Path(scope["verification_root"])
    _require(verifier.is_absolute() and verifier.is_dir(), "verification_root must be an existing directory")
    _require(not workspace.is_relative_to(verifier) and not verifier.is_relative_to(workspace),
             "verification_root must be outside the workspace")
    _require(isinstance(scope["source_read_roots"], list) and bool(scope["source_read_roots"]),
             "source_read_roots must be a nonempty list")
    for root in scope["source_read_roots"]:
        _require(isinstance(root, str) and Path(root).is_absolute() and Path(root).is_dir(),
                 "source_read_roots must name existing absolute directories")
    _require(isinstance(scope["executables"], dict) and bool(scope["executables"]),
             "executables must be a nonempty mapping")
    for name, path in scope["executables"].items():
        _require(isinstance(name, str) and bool(name), "executable names must be nonempty")
        _absolute_file(path, f"executable {name}")

    agents = scope["agents"]
    _require(isinstance(agents, dict) and bool(agents), "agents must be a nonempty mapping")
    plan_adapters = set()
    for workpack in plan["workpacks"]:
        if workpack.get("executor") == "AGENT":
            _require(isinstance(workpack.get("agent"), dict), "AGENT workpack needs agent")
            plan_adapters.add(workpack["agent"].get("adapter"))
    _require("CODEX" not in plan_adapters, "plan 1.3 cannot use CODEX")
    for name, definition in agents.items():
        _require(isinstance(name, str) and isinstance(definition, dict), "agent definitions must be objects")
        _require(set(definition) <= AGENT_FIELDS, "agent definition has unsupported fields")
        _require(definition.get("adapter") in plan_adapters, "agent adapter is not declared by the plan")
        adapter = definition.get("adapter")
        if adapter == "deepseek-api":
            _require(isinstance(definition.get("base_url"), str) and definition["base_url"].strip(),
                     "deepseek-api needs base_url")
            if "key_file" in definition:
                _absolute_file(definition["key_file"], f"agent {name} key_file")
        elif adapter in {"dsh-headless", "fixture-agent"}:
            _require(isinstance(definition.get("executable"), str), "agent executable is required")
            _absolute_file(definition["executable"], f"agent {name} executable")
        else:
            _require(isinstance(definition.get("executable"), str), "agent executable is required")
            _absolute_file(definition["executable"], f"agent {name} executable")
        if "session" in definition:
            _require(isinstance(definition["session"], dict), "agent session must be an object")
        if "model" in definition:
            _require(isinstance(definition["model"], dict), "agent model must be an object")

    sandbox = scope["sandbox"]
    _require(isinstance(sandbox, dict) and set(sandbox) == SANDBOX_FIELDS,
             "sandbox must contain provider and network")
    _require(sandbox["provider"] in PROVIDERS, "unsupported sandbox provider")
    if sandbox["provider"] == "none":
        _require(test_only is True, "none provider is test-only; production needs seatbelt/bwrap")
    network = sandbox["network"]
    _require(isinstance(network, dict) and set(network) == {"agent_egress", "task_network"},
             "sandbox.network must declare agent_egress and task_network")
    _require(network["agent_egress"] in {"NONE", "MODEL_ONLY"}, "unsupported agent egress")
    _require(network["task_network"] in {"NONE", "LOOPBACK", "REMOTE_SERVICE"}, "unsupported task network")

    for field in ("max_attempts", "max_task_attempts", "command_timeout_seconds"):
        _require(type(scope[field]) is int and scope[field] > 0, f"{field} must be positive")
    _require(scope["usage_accounting"] in {"ADAPTER_REPORTED", "UNKNOWN"}, "unsupported usage_accounting")
    _require(isinstance(scope["expires_at"], str) and scope["expires_at"].strip(), "expires_at is required")

    tasks = {workpack["workpack_id"]: workpack for workpack in plan["workpacks"]}
    writes = scope["task_write_roots"]
    _require(isinstance(writes, dict) and set(writes) == set(tasks), "every workpack needs write roots")
    for workpack_id, workpack in tasks.items():
        roots = writes[workpack_id]
        _require(isinstance(roots, list) and bool(roots), "task write roots must be nonempty")
        resolved = []
        for root in roots:
            path = Path(root)
            _require(path.is_absolute() and path.is_dir() and path.is_relative_to(workspace),
                     "task write roots must be existing workspace directories")
            resolved.append(path)
        for artifact in workpack["artifacts"]:
            target = _relative_under(workspace, artifact["path"], "artifact path")
            _require(any(target.is_relative_to(root) for root in resolved),
                     "artifact is outside the task write roots")
        if workpack["executor"] == "LOCAL":
            _require(workpack.get("local_argv") and workpack["local_argv"][0] in scope["executables"],
                     "LOCAL workpack needs a declared executable")
        for check in workpack["verification"]:
            _require(check["argv"][0] in scope["executables"], "verification executable is not declared")
    return scope


def run_agent_workpack(plan, scope, workpack_id, *, adapter, provider, prompt, before_dispatch=None):
    """Dispatch one AGENT workpack through an explicitly supplied adapter/provider."""
    validate_scope_13(plan, scope)
    _require(provider is not None, "AGENT dispatch requires a sandbox provider")
    if getattr(adapter, "provider", None) is None:
        adapter.provider = provider
    workpack = next((row for row in plan["workpacks"] if row["workpack_id"] == workpack_id), None)
    _require(workpack is not None and workpack.get("executor") == "AGENT", "workpack is not AGENT")
    workspace = Path(scope["workspace_root"])
    original = before_dispatch or (lambda: None)
    calls = []

    def dispatch_hook():
        calls.append(True)
        original()

    command = SimpleNamespace(scope=SimpleNamespace(
        cwd=workspace,
        read_roots=(workspace, *[Path(root) for root in scope["source_read_roots"]]),
        write_roots=tuple(Path(root) for root in scope["task_write_roots"][workpack_id]),
        timeout_seconds=scope["command_timeout_seconds"],
        environment={},
    ))
    result = adapter.run(AgentRequest(command=command, prompt=prompt),
                         before_dispatch=dispatch_hook)
    return {**result, "workpack_id": workpack_id, "before_dispatch_calls": len(calls)}
