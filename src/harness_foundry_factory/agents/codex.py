"""Codex CLI adapter and Codex sandbox provider (M1.1 package).

Both classes delegate to the existing receivers so behavior stays byte-for-byte
compatible. Extraction of argv/event parsing into these classes is M1.1.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .base import (
    ADAPTER_PROBE_FAILED,
    SANDBOX_UNAVAILABLE,
    AgentCapabilities,
    AgentRequest,
)

REQUIRED_EXEC_FLAGS = (
    "--ignore-user-config",
    "--strict-config",
    "--ephemeral",
    "--json",
    "--cd",
    "stdin",
)


def _identity(path: Path) -> dict:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"executable": str(path), "executable_sha256": digest}


class CodexCliAdapter:
    """Adapter for the existing Codex CLI receiver."""

    capabilities = AgentCapabilities(
        adapter_id="codex-cli",
        adapter_version="1",
        prompt_transport="stdin",
        events="jsonl",
        usage="REPORTED",
        defaults="READABLE",
        handoff=True,
        sandbox="PROVIDER",
    )

    def __init__(self, executable: str | Path):
        self.executable = Path(executable)

    def probe(self, executable: Path | None = None) -> dict:
        path = Path(executable or self.executable)
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            return {"status": "FAIL", "reason_code": ADAPTER_PROBE_FAILED,
                    "diagnostic": "executable must be an absolute executable file",
                    "adapter_id": self.capabilities.adapter_id}
        try:
            observed = subprocess.run(
                [str(path), "exec", "--help"], capture_output=True, text=True,
                timeout=15, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "FAIL", "reason_code": ADAPTER_PROBE_FAILED,
                    "diagnostic": str(exc), **_identity(path),
                    "adapter_id": self.capabilities.adapter_id}
        text = observed.stdout + observed.stderr
        missing = [flag for flag in REQUIRED_EXEC_FLAGS if flag not in text]
        passed = observed.returncode == 0 and not missing
        return {
            "status": "PASS" if passed else "FAIL",
            "reason_code": None if passed else ADAPTER_PROBE_FAILED,
            "adapter_id": self.capabilities.adapter_id,
            "adapter_version": self.capabilities.adapter_version,
            "interface_checked": True,
            "required_flags": list(REQUIRED_EXEC_FLAGS),
            "missing_flags": missing,
            "returncode": observed.returncode,
            **_identity(path),
        }

    def run(self, request: AgentRequest, *, before_dispatch, **hooks) -> dict:
        from harness_foundry_factory.coding_process import CodexCodingRunner
        return CodexCodingRunner(self.executable).run(
            request.command, before_dispatch=before_dispatch, **hooks)


class CodexSandboxProvider:
    """SandboxProvider backed by the existing `codex sandbox` receiver."""

    provider_id = "codex-sandbox"

    def __init__(self, executable: str | Path, *, runner_class=None):
        self.executable = Path(executable)
        self._runner_class = runner_class

    def probe(self) -> dict:
        path = self.executable
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            return {"status": "FAIL", "reason_code": SANDBOX_UNAVAILABLE,
                    "provider_id": self.provider_id,
                    "diagnostic": "codex sandbox receiver is not executable"}
        return {"status": "PASS", "provider_id": self.provider_id, **_identity(path)}

    def run(self, command, *, before_dispatch, **hooks) -> dict:
        runner_class = self._runner_class
        if runner_class is None:
            from harness_foundry_factory.local_process import CodexSandboxRunner as runner_class
        return runner_class(self.executable).run(
            command, before_dispatch=before_dispatch, **hooks)

__all__ = ["REQUIRED_EXEC_FLAGS", "CodexCliAdapter", "CodexSandboxProvider"]
