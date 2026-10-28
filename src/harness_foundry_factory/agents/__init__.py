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
from .api import DeepseekApiAdapter
from .profile import DeclarativeAdapter, DeclarativeProfile, ProfileError
from .sandbox_none import NoneSandboxProvider
from .sandbox_seatbelt import SeatbeltSandboxProvider
from .sandbox_bwrap import BubblewrapSandboxProvider
from .sandbox_trusted import TrustedHostProvider
from .scope13 import run_agent_workpack, validate_scope_13
from .agent_controller import AgentBuildController
from .egress_proxy import AllowlistProxy
from .host_gateway import HostApiGateway
from .artifacts import ArtifactStoreError, ingest as ingest_artifacts, write_manifest
from .limits import preexec, truncate_output
from .verifier import VerifierContract, VerifierContractError
from .verifier_runner import run_verifier

__all__ = [
    "ADAPTER_PROBE_FAILED", "ADAPTER_PROTOCOL_ERROR", "ADAPTER_UNSUPPORTED_CAPABILITY",
    "ADAPTER_USAGE_UNKNOWN", "AGENT_HANDOFF_INVALID", "AGENT_SANDBOXES", "DEFAULTS_SOURCES",
    "EVENT_FORMATS", "PROMPT_TRANSPORTS", "SANDBOX_NETWORK_UNSUPPORTED", "SANDBOX_UNAVAILABLE",
    "USAGE_SOURCES", "AgentAdapter", "AgentCapabilities", "AgentRequest", "SandboxProvider",
    "CodexCliAdapter", "CodexSandboxProvider", "DshHeadlessAdapter", "DeepseekApiAdapter", "DeclarativeAdapter", "DeclarativeProfile", "ProfileError", "NoneSandboxProvider", "SeatbeltSandboxProvider", "BubblewrapSandboxProvider", "TrustedHostProvider", "run_agent_workpack", "validate_scope_13", "AgentBuildController", "AllowlistProxy", "HostApiGateway", "ArtifactStoreError", "ingest_artifacts", "write_manifest", "preexec", "truncate_output", "VerifierContract", "VerifierContractError", "run_verifier",
]
