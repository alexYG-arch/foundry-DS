"""Declarative agent profile: data-only adapter definition, no model calls.

M2.0 scope: load/validate a profile, probe an executable, render argv, and map
events/exit codes. Actual dispatch remains behind a SandboxProvider and is not
enabled by this module.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import (
    ADAPTER_PROBE_FAILED,
    ADAPTER_PROTOCOL_ERROR,
    AgentCapabilities,
)


PROFILE_SCHEMA = "1.0"
FOUNDRY_EVENTS = frozenset({
    "TURN_STARTED", "MESSAGE", "TOOL_CALL", "TOOL_RESULT", "USAGE", "RETRY",
    "TURN_COMPLETED", "TURN_FAILED", "UNKNOWN",
})
PLACEHOLDERS = frozenset({"executable", "workspace", "prompt_file", "prompt"})
PROFILE_KEYS = frozenset({
    "schema_version", "adapter_id", "adapter_version", "capabilities", "probe",
    "invocation", "event_map", "exit_map", "unknown_event",
})
CAPABILITY_KEYS = frozenset({"prompt_transport", "events", "usage", "defaults", "handoff", "sandbox"})


class ProfileError(ValueError):
    """Invalid declarative profile; fail closed before any process starts."""


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field} must be a nonempty string")
    return value


def _text_list(value, field):
    if not isinstance(value, list) or not value or not all(isinstance(x, str) and x for x in value):
        raise ProfileError(f"{field} must be a nonempty text list")
    return list(value)


def _check_placeholders(value, field):
    if not isinstance(value, str):
        raise ProfileError(f"{field} must be text")
    try:
        parts = re.findall(r"\{([^{}]+)\}", value)
    except re.error as exc:
        raise ProfileError(f"{field} has invalid braces: {exc}") from exc
    unknown = set(parts) - PLACEHOLDERS
    if unknown:
        raise ProfileError(f"{field} has unsupported placeholders: {sorted(unknown)}")
    if value.count("{") != len(parts) or value.count("}") != len(parts):
        raise ProfileError(f"{field} has unbalanced placeholders")


def render_argv(template, *, executable: str, workspace: str, prompt_file: str = "", prompt: str = ""):
    """Render a fixed argv list without shell evaluation."""
    context = {"executable": executable, "workspace": workspace,
               "prompt_file": prompt_file, "prompt": prompt}
    rendered = []
    for item in template:
        _check_placeholders(item, "argv item")
        for key in re.findall(r"\{([^{}]+)\}", item):
            if key == "prompt" and "\x00" in context["prompt"]:
                raise ProfileError("prompt contains NUL")
        rendered.append(item.format_map(context))
    return rendered


def _parse_event_map(value):
    if not isinstance(value, list) or not value:
        raise ProfileError("event_map must be a nonempty list")
    result = []
    for index, row in enumerate(value):
        if not isinstance(row, dict) or set(row) != {"when", "emit"}:
            raise ProfileError(f"event_map[{index}] must contain when/emit")
        when, emit = row["when"], row["emit"]
        if not isinstance(when, dict) or set(when) != {"type"}:
            raise ProfileError(f"event_map[{index}].when must contain type")
        _text(when["type"], f"event_map[{index}].when.type")
        if emit not in FOUNDRY_EVENTS:
            raise ProfileError(f"event_map[{index}].emit is not a Foundry event")
        result.append({"when": {"type": when["type"]}, "emit": emit})
    return result


def _parse_exit_map(value):
    if not isinstance(value, dict) or not value:
        raise ProfileError("exit_map must be a nonempty object")
    if any(key not in {"0", "!0"} for key in value):
        raise ProfileError("exit_map only accepts 0 and !0")
    if any(status not in {"PASS", "FAIL"} for status in value.values()):
        raise ProfileError("exit_map values must be PASS or FAIL")
    return dict(value)


@dataclass(frozen=True)
class DeclarativeProfile:
    adapter_id: str
    adapter_version: str
    capabilities: AgentCapabilities
    probe_argv: tuple[str, ...]
    probe_regex: str
    invocation_argv: tuple[str, ...]
    invocation_stdin: str | None
    event_map: tuple[dict, ...]
    exit_map: dict
    unknown_event: str

    @classmethod
    def from_dict(cls, value: Any):
        if not isinstance(value, dict):
            raise ProfileError("profile must be an object")
        if set(value) != PROFILE_KEYS:
            raise ProfileError(f"profile fields differ: {sorted(set(value) ^ PROFILE_KEYS)}")
        if value.get("schema_version") != PROFILE_SCHEMA:
            raise ProfileError(f"schema_version must be {PROFILE_SCHEMA}")
        adapter_id = _text(value.get("adapter_id"), "adapter_id")
        adapter_version = _text(value.get("adapter_version"), "adapter_version")
        capabilities = value.get("capabilities")
        if not isinstance(capabilities, dict) or set(capabilities) != CAPABILITY_KEYS:
            raise ProfileError("capabilities fields are invalid")
        try:
            capabilities_obj = AgentCapabilities(
                adapter_id=adapter_id, adapter_version=adapter_version,
                prompt_transport=capabilities["prompt_transport"],
                events=capabilities["events"], usage=capabilities["usage"],
                defaults=capabilities["defaults"], handoff=capabilities["handoff"],
                sandbox=capabilities["sandbox"],
            )
            capabilities_obj.validate()
        except (KeyError, ValueError) as exc:
            raise ProfileError(f"invalid capabilities: {exc}") from exc

        probe = value.get("probe")
        if not isinstance(probe, dict) or set(probe) != {"argv", "expect_regex"}:
            raise ProfileError("probe must contain argv/expect_regex")
        probe_argv = _text_list(probe["argv"], "probe.argv")
        if not any("{executable}" in item for item in probe_argv):
            raise ProfileError("probe.argv must contain {executable}")
        for item in probe_argv:
            _check_placeholders(item, "probe.argv item")
        try:
            re.compile(probe["expect_regex"])
        except (re.error, TypeError) as exc:
            raise ProfileError(f"probe.expect_regex is invalid: {exc}") from exc
        _text(probe["expect_regex"], "probe.expect_regex")

        invocation = value.get("invocation")
        if not isinstance(invocation, dict) or set(invocation) not in ({"argv", "stdin"}, {"argv"}):
            raise ProfileError("invocation must contain argv and optional stdin")
        invocation_argv = _text_list(invocation["argv"], "invocation.argv")
        for item in invocation_argv:
            _check_placeholders(item, "invocation.argv item")
        stdin = invocation.get("stdin")
        if stdin is not None and stdin != "{prompt}":
            raise ProfileError("invocation.stdin must be {prompt} or absent")

        event_map = _parse_event_map(value.get("event_map"))
        exit_map = _parse_exit_map(value.get("exit_map"))
        unknown = value.get("unknown_event")
        if unknown != "RETAIN":
            raise ProfileError("unknown_event must be RETAIN")

        return cls(
            adapter_id=adapter_id, adapter_version=adapter_version,
            capabilities=capabilities_obj, probe_argv=tuple(probe_argv),
            probe_regex=probe["expect_regex"],
            invocation_argv=tuple(invocation_argv), invocation_stdin=stdin,
            event_map=tuple(event_map), exit_map=exit_map, unknown_event=unknown,
        )

    @classmethod
    def load(cls, path: str | Path):
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileError(f"cannot read profile: {exc}") from exc
        return cls.from_dict(value)


class DeclarativeAdapter:
    """Declarative adapter; dispatch requires an explicit provider and executable."""

    def __init__(self, profile: DeclarativeProfile, *, executable=None, provider=None):
        self.profile = profile
        self.capabilities = profile.capabilities
        self.executable = Path(executable) if executable is not None else None
        self.provider = provider

    @classmethod
    def load(cls, path, **kwargs):
        return cls(DeclarativeProfile.load(path), **kwargs)

    def probe(self, executable: Path | None = None) -> dict:
        if executable is None:
            return {"status": "FAIL", "reason_code": ADAPTER_PROBE_FAILED,
                    "adapter_id": self.capabilities.adapter_id,
                    "diagnostic": "declarative probe requires an explicit executable"}
        path = Path(executable)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            return {"status": "FAIL", "reason_code": ADAPTER_PROBE_FAILED,
                    "adapter_id": self.capabilities.adapter_id,
                    "diagnostic": "executable must be an absolute executable file"}
        argv = render_argv(self.profile.probe_argv, executable=str(path), workspace=str(path.parent))
        try:
            observed = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "FAIL", "reason_code": ADAPTER_PROBE_FAILED,
                    "adapter_id": self.capabilities.adapter_id, "diagnostic": str(exc)}
        matched = re.search(self.profile.probe_regex, observed.stdout + observed.stderr) is not None
        passed = observed.returncode == 0 and matched
        return {
            "status": "PASS" if passed else "FAIL",
            "reason_code": None if passed else ADAPTER_PROBE_FAILED,
            "adapter_id": self.capabilities.adapter_id,
            "adapter_version": self.capabilities.adapter_version,
            "interface_checked": True,
            "returncode": observed.returncode,
            "regex_matched": matched,
        }

    def render(self, *, executable, workspace, prompt="", prompt_file="") -> dict:
        argv = render_argv(self.profile.invocation_argv, executable=str(executable),
                           workspace=str(workspace), prompt=prompt, prompt_file=prompt_file)
        return {"argv": argv, "stdin": prompt if self.profile.invocation_stdin else None,
                "cwd": str(workspace)}

    def map_event(self, raw_type: str) -> str:
        for row in self.profile.event_map:
            if row["when"]["type"] == raw_type:
                return row["emit"]
        return "UNKNOWN"

    def classify_exit(self, code: int) -> str:
        key = "0" if code == 0 else "!0"
        return self.profile.exit_map.get(key, "FAIL")

    def run(self, request, *, before_dispatch, **hooks):
        """Render and dispatch through an explicitly supplied SandboxProvider.

        No provider means no dispatch. M2.1a only supports a test provider; the
        controller integration remains M2.1b.
        """
        if self.provider is None or self.executable is None:
            raise NotImplementedError("declarative dispatch requires executable and provider")
        scope = getattr(request.command, "scope", request.command)
        cwd = Path(getattr(scope, "cwd", "")).resolve()
        rendered = self.render(executable=self.executable, workspace=str(cwd),
                               prompt=request.prompt, prompt_file="")
        from harness_foundry_factory.local_process import LocalCommand
        command = LocalCommand.prepare(
            argv=rendered["argv"], cwd=str(cwd),
            read_roots=getattr(scope, "read_roots", (cwd,)),
            write_roots=getattr(scope, "write_roots", (cwd,)),
            timeout_seconds=getattr(scope, "timeout_seconds", 1800),
            environment=getattr(scope, "environment", None),
        )
        return self.provider.run(command, before_dispatch=before_dispatch,
                                 stdin=rendered["stdin"], **hooks)
