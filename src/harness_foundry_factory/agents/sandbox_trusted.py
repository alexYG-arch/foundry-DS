"""Trusted-host execution provider for Contract Independence (no syscall sandbox)."""

from __future__ import annotations

import subprocess

from .base import SANDBOX_NETWORK_UNSUPPORTED
from .limits import preexec, truncate_output


class TrustedHostProvider:
    """Run commands directly on a trusted host.

    This is not a sandbox. It is the v3 baseline execution mode; callers must
    label it ``CONTRACT_INDEPENDENCE`` and must not report sandbox PASS.
    """

    provider_id = "trusted-host"
    assurance = "CONTRACT_INDEPENDENCE"

    def __init__(self, *, allow_trusted_host=True):
        self.allow_trusted_host = allow_trusted_host

    def probe(self):
        return {"status": "PASS" if self.allow_trusted_host else "FAIL",
                "provider_id": self.provider_id, "sandbox_enforcement": "NONE",
                "assurance": self.assurance, "network_mode": "NONE"}

    def run(self, command, *, before_dispatch, stdin=None, **hooks):
        if not self.allow_trusted_host:
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": "TRUSTED_HOST_NOT_ALLOWED", "workload_started": False}
        if getattr(command, "network", None) not in (None, {"mode": "NONE"}):
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_NETWORK_UNSUPPORTED, "workload_started": False}
        before_dispatch()
        max_cpu = getattr(command, "max_cpu_seconds", None)
        max_memory = getattr(command, "max_memory_bytes", None)
        max_fds = getattr(command, "max_fds", None)
        max_output = getattr(command, "max_output_bytes", None)
        preexec_fn = preexec(max_cpu, max_memory, max_fds) if (max_cpu or max_memory or max_fds) else None
        try:
            observed = subprocess.run(
                list(command.argv), cwd=str(command.cwd), input=stdin, text=True,
                capture_output=True, timeout=command.timeout_seconds, preexec_fn=preexec_fn,
                env=dict(command.environment) if command.environment else None, check=False)
        except subprocess.TimeoutExpired as exc:
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": "SANDBOX_TIMEOUT", "workload_started": True, "diagnostic": str(exc)}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": "TRUSTED_HOST_EXEC_FAILED", "workload_started": True, "diagnostic": str(exc)}
        return {"status": "PASS" if observed.returncode == 0 else "FAIL",
                "provider_id": self.provider_id, "sandbox_enforcement": "NONE",
                "assurance": self.assurance, "network_mode": "NONE",
                "exit_code": observed.returncode, "stdout": truncate_output(observed.stdout, max_output),
                "stderr": truncate_output(observed.stderr, max_output), "workload_started": True,
                "workpack_accepted": False}
