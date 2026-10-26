"""Agent adapter and sandbox provider contract (M0/M1.1 package).

This module is the seam between the controller and an external agent runtime.
It intentionally contains no Codex-specific behavior and no model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


ADAPTER_PROBE_FAILED = "ADAPTER_PROBE_FAILED"
ADAPTER_PROTOCOL_ERROR = "ADAPTER_PROTOCOL_ERROR"
ADAPTER_USAGE_UNKNOWN = "ADAPTER_USAGE_UNKNOWN"
ADAPTER_UNSUPPORTED_CAPABILITY = "ADAPTER_UNSUPPORTED_CAPABILITY"
SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
SANDBOX_NETWORK_UNSUPPORTED = "SANDBOX_NETWORK_UNSUPPORTED"
AGENT_HANDOFF_INVALID = "AGENT_HANDOFF_INVALID"

PROMPT_TRANSPORTS = frozenset({"stdin", "arg", "file", "http"})
EVENT_FORMATS = frozenset({"jsonl", "text"})
USAGE_SOURCES = frozenset({"REPORTED", "UNKNOWN"})
DEFAULTS_SOURCES = frozenset({"READABLE", "EXPLICIT_ONLY"})
AGENT_SANDBOXES = frozenset({"PROVIDER", "NATIVE", "NONE"})


@dataclass(frozen=True)
class AgentCapabilities:
    adapter_id: str
    adapter_version: str
    prompt_transport: str
    events: str
    usage: str
    defaults: str
    handoff: bool
    sandbox: str

    def validate(self) -> None:
        if not self.adapter_id or not self.adapter_version:
            raise ValueError("adapter id and version must be nonempty")
        if self.prompt_transport not in PROMPT_TRANSPORTS:
            raise ValueError(f"unsupported prompt transport: {self.prompt_transport}")
        if self.events not in EVENT_FORMATS:
            raise ValueError(f"unsupported event format: {self.events}")
        if self.usage not in USAGE_SOURCES:
            raise ValueError(f"unsupported usage source: {self.usage}")
        if self.defaults not in DEFAULTS_SOURCES:
            raise ValueError(f"unsupported defaults source: {self.defaults}")
        if type(self.handoff) is not bool:
            raise ValueError("handoff must be boolean")
        if self.sandbox not in AGENT_SANDBOXES:
            raise ValueError(f"unsupported agent sandbox: {self.sandbox}")


@dataclass(frozen=True)
class AgentRequest:
    """M1.0 request shape; command is a validated LocalCommand/CodingCommand."""

    command: Any
    prompt: str
    model: str | None = None
    reasoning_effort: str | None = None
    model_policy: str = "FIXED"
    model_service: dict | None = None
    model_defaults_source: dict | None = None


@runtime_checkable
class AgentAdapter(Protocol):
    capabilities: AgentCapabilities

    def probe(self, executable: Path | None = None) -> dict: ...

    def run(self, request: AgentRequest, *, before_dispatch, **hooks) -> dict: ...


@runtime_checkable
class SandboxProvider(Protocol):
    provider_id: str

    def probe(self) -> dict: ...

    def run(self, command, *, before_dispatch, **hooks) -> dict: ...

__all__ = [
    "ADAPTER_PROBE_FAILED", "ADAPTER_PROTOCOL_ERROR", "ADAPTER_USAGE_UNKNOWN",
    "ADAPTER_UNSUPPORTED_CAPABILITY", "SANDBOX_UNAVAILABLE", "SANDBOX_NETWORK_UNSUPPORTED",
    "AGENT_HANDOFF_INVALID", "PROMPT_TRANSPORTS", "EVENT_FORMATS", "USAGE_SOURCES",
    "DEFAULTS_SOURCES", "AGENT_SANDBOXES", "AgentCapabilities", "AgentRequest",
    "AgentAdapter", "SandboxProvider",
]
