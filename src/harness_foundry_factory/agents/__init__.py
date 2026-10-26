"""Agent adapter/sandbox package (M1.1)."""

from .base import (
    ADAPTER_PROBE_FAILED,
    ADAPTER_PROTOCOL_ERROR,
    ADAPTER_UNSUPPORTED_CAPABILITY,
    ADAPTER_USAGE_UNKNOWN,
    AGENT_HANDOFF_INVALID,
    AGENT_SANDBOXES,
    DEFAULTS_SOURCES,
    EVENT_FORMATS,
    PROMPT_TRANSPORTS,
    SANDBOX_NETWORK_UNSUPPORTED,
    SANDBOX_UNAVAILABLE,
    USAGE_SOURCES,
    AgentAdapter,
    AgentCapabilities,
    AgentRequest,
    SandboxProvider,
)
from .codex import CodexCliAdapter, CodexSandboxProvider
from .dsh import DshHeadlessAdapter
from .profile import DeclarativeAdapter, DeclarativeProfile, ProfileError
from .sandbox_none import NoneSandboxProvider
from .sandbox_seatbelt import SeatbeltSandboxProvider
from .scope13 import run_agent_workpack, validate_scope_13

__all__ = [
    "ADAPTER_PROBE_FAILED", "ADAPTER_PROTOCOL_ERROR", "ADAPTER_UNSUPPORTED_CAPABILITY",
    "ADAPTER_USAGE_UNKNOWN", "AGENT_HANDOFF_INVALID", "AGENT_SANDBOXES", "DEFAULTS_SOURCES",
    "EVENT_FORMATS", "PROMPT_TRANSPORTS", "SANDBOX_NETWORK_UNSUPPORTED", "SANDBOX_UNAVAILABLE",
    "USAGE_SOURCES", "AgentAdapter", "AgentCapabilities", "AgentRequest", "SandboxProvider",
    "CodexCliAdapter", "CodexSandboxProvider", "DshHeadlessAdapter", "DeclarativeAdapter", "DeclarativeProfile", "ProfileError", "NoneSandboxProvider", "SeatbeltSandboxProvider", "run_agent_workpack", "validate_scope_13",
]
