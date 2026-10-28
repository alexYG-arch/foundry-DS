"""Linux bubblewrap sandbox provider for task commands (Plan 1.3 A/Linux)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .base import SANDBOX_NETWORK_UNSUPPORTED, SANDBOX_UNAVAILABLE


class BubblewrapSandboxProvider:
    provider_id = "bwrap"

    def __init__(self, executable=None):
        self.executable = Path(executable) if executable is not None else Path(shutil.which("bwrap") or "")

    def probe(self):
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            return {"status": "FAIL", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_UNAVAILABLE, "diagnostic": "bwrap is not executable"}
        try:
            version = subprocess.run([str(self.executable), "--version"], capture_output=True, text=True,
                                     timeout=15, check=False)
            echo = subprocess.run(
                [str(self.executable), "--unshare-net", "--ro-bind", "/", "/", "--dev", "/dev",
                 "--proc", "/proc", "--", "/bin/echo", "bwrap_ok"],
                capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "FAIL", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_UNAVAILABLE, "diagnostic": str(exc)}
        passed = version.returncode == 0 and echo.returncode == 0 and echo.stdout.strip() == "bwrap_ok"
        return {"status": "PASS" if passed else "FAIL", "provider_id": self.provider_id,
                "reason_code": None if passed else SANDBOX_UNAVAILABLE,
                "sandbox_enforcement": "BWRAP", "network_mode": "NONE",
                "version": version.stdout.strip()}

    def _argv(self, command):
        argv = [str(self.executable), "--die-with-parent", "--unshare-net", "--ro-bind", "/", "/",
                "--dev", "/dev", "--proc", "/proc"]
        for root in getattr(command, "write_roots", ()) or ():
            path = Path(root).resolve()
            if path == Path("/"):
                raise ValueError("bwrap write root cannot be /")
            argv.extend(["--bind", str(path), str(path)])
        argv.extend(["--chdir", str(Path(command.cwd).resolve()), "--", *[str(value) for value in command.argv]])
        return argv

    def run(self, command, *, before_dispatch, stdin=None, **hooks):
        probe = self.probe()
        if probe["status"] != "PASS":
            return {**probe, "status": "VALIDATION_FAILED", "workload_started": False}
        if getattr(command, "network", None) not in (None, {"mode": "NONE"}):
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_NETWORK_UNSUPPORTED, "workload_started": False}
        try:
            argv = self._argv(command)
        except ValueError as exc:
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_UNAVAILABLE, "diagnostic": str(exc), "workload_started": False}
        before_dispatch()
        try:
            observed = subprocess.run(
                argv, cwd=str(command.cwd), input=stdin, text=True, capture_output=True,
                timeout=command.timeout_seconds,
                env=dict(command.environment) if command.environment else None, check=False)
        except subprocess.TimeoutExpired as exc:
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": "SANDBOX_TIMEOUT", "workload_started": True, "diagnostic": str(exc)}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_UNAVAILABLE, "workload_started": True, "diagnostic": str(exc)}
        return {"status": "PASS" if observed.returncode == 0 else "FAIL", "provider_id": self.provider_id,
                "sandbox_enforcement": "BWRAP", "network_mode": "NONE",
                "exit_code": observed.returncode, "stdout": observed.stdout, "stderr": observed.stderr,
                "workload_started": True, "workpack_accepted": False}
