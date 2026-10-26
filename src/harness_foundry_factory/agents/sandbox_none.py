"""Test-only unsandboxed provider; never a production fallback (ADR-0002)."""

from __future__ import annotations

import subprocess

from .base import SANDBOX_NETWORK_UNSUPPORTED, SANDBOX_UNAVAILABLE


class NoneSandboxProvider:
    """Runs a command only when explicitly allowed and network is NONE.

    This provider gives no filesystem or network isolation. It exists for the
    fixture E2E and tests; production requires codex-sandbox or agent-native
    sandboxing.
    """

    provider_id = "none"

    def __init__(self, *, allow_unsandboxed_agent: bool, network_mode: str = "NONE"):
        self.allow_unsandboxed_agent = allow_unsandboxed_agent
        self.network_mode = network_mode

    def probe(self) -> dict:
        if self.allow_unsandboxed_agent is not True:
            return {"status": "FAIL", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_UNAVAILABLE,
                    "diagnostic": "allow_unsandboxed_agent is not true"}
        if self.network_mode != "NONE":
            return {"status": "FAIL", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_NETWORK_UNSUPPORTED,
                    "diagnostic": "none provider only supports network NONE"}
        return {"status": "PASS", "provider_id": self.provider_id,
                "sandbox_enforcement": "NONE", "network_mode": "NONE"}

    def run(self, command, *, before_dispatch, stdin=None, **hooks) -> dict:
        probe = self.probe()
        if probe["status"] != "PASS":
            return {**probe, "status": "VALIDATION_FAILED", "workload_started": False}
        if getattr(command, "network", None) not in (None, {"mode": "NONE"}):
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_NETWORK_UNSUPPORTED,
                    "workload_started": False}
        before_dispatch()
        try:
            observed = subprocess.run(
                list(command.argv), cwd=str(command.cwd), input=stdin, text=True,
                capture_output=True, timeout=command.timeout_seconds,
                env=dict(command.environment) if command.environment else None,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_UNAVAILABLE, "workload_started": True,
                    "diagnostic": str(exc)}
        return {
            "status": "PASS" if observed.returncode == 0 else "FAIL",
            "provider_id": self.provider_id,
            "sandbox_enforcement": "NONE",
            "network_mode": "NONE",
            "exit_code": observed.returncode,
            "stdout": observed.stdout,
            "stderr": observed.stderr,
            "workload_started": True,
            "workpack_accepted": False,
        }
