"""macOS seatbelt sandbox provider (A: host-native path).

This provider runs a command under `/usr/bin/sandbox-exec` with a generated
profile. It gives no network to task commands by default and confines writes to
the validated write roots. It fails closed if seatbelt is unavailable.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .base import SANDBOX_NETWORK_UNSUPPORTED, SANDBOX_UNAVAILABLE

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
SYSTEM_READ_ROOTS = (
    "/usr", "/bin", "/sbin", "/System", "/Library", "/private/etc",
    "/dev",
)


def _quote(value: str) -> str:
    if any(char in value for char in ('"', "\n", "\r", "\x00")):
        raise ValueError("seatbelt path contains an unsupported character")
    return f'"{value}"'


def _canonical(path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved == Path("/"):
        raise ValueError("seatbelt write root cannot be /")
    return resolved


class SeatbeltSandboxProvider:
    """Run argv under a deny-default seatbelt profile."""

    provider_id = "seatbelt"

    def __init__(self, *, executable: str | Path = SANDBOX_EXEC):
        self.executable = Path(executable)

    def probe(self) -> dict:
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            return {"status": "FAIL", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_UNAVAILABLE,
                    "diagnostic": "sandbox-exec is not executable"}
        profile = "(version 1)\n(allow default)\n"
        with tempfile.TemporaryDirectory(prefix="foundry-seatbelt-probe-") as directory:
            profile_path = Path(directory) / "probe.sb"
            profile_path.write_text(profile, encoding="utf-8")
            try:
                observed = subprocess.run(
                    [str(self.executable), "-f", str(profile_path), "/bin/echo", "seatbelt_ok"],
                    capture_output=True, text=True, timeout=15, check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return {"status": "FAIL", "provider_id": self.provider_id,
                        "reason_code": SANDBOX_UNAVAILABLE, "diagnostic": str(exc)}
        passed = observed.returncode == 0 and observed.stdout.strip() == "seatbelt_ok"
        return {
            "status": "PASS" if passed else "FAIL",
            "provider_id": self.provider_id,
            "reason_code": None if passed else SANDBOX_UNAVAILABLE,
            "sandbox_enforcement": "SEATBELT",
            "network_mode": "NONE",
            "returncode": observed.returncode,
        }

    def _profile(self, reads, writes) -> str:
        read_paths = list(SYSTEM_READ_ROOTS)
        seen = set()
        for value in [*reads, *writes]:
            path = _canonical(value)
            if str(path) not in seen:
                read_paths.append(str(path))
                seen.add(str(path))
        write_paths = []
        for value in writes:
            path = _canonical(value)
            if str(path) not in write_paths:
                write_paths.append(str(path))
        read_rules = "\n".join(f"  (subpath {_quote(path)})" for path in read_paths)
        write_rules = "\n".join(f"  (subpath {_quote(path)})" for path in write_paths)
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            "(allow signal (target self))",
            f"(allow file-read*\n  (literal \"/\")\n{read_rules}\n)",
            "(allow file-write-data (literal \"/dev/null\"))",
        ]
        if write_rules:
            lines.append(f"(allow file-write*\n{write_rules}\n)")
        return "\n".join(lines) + "\n"

    def run(self, command, *, before_dispatch, stdin=None, **hooks) -> dict:
        probe = self.probe()
        if probe["status"] != "PASS":
            return {**probe, "status": "VALIDATION_FAILED", "workload_started": False}
        network = getattr(command, "network", None)
        if network not in (None, {"mode": "NONE"}):
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_NETWORK_UNSUPPORTED,
                    "diagnostic": "seatbelt task network is NONE in P1",
                    "workload_started": False}
        try:
            profile = self._profile(
                getattr(command, "read_roots", ()) or (),
                getattr(command, "write_roots", ()) or (),
            )
        except ValueError as exc:
            return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                    "reason_code": SANDBOX_UNAVAILABLE, "diagnostic": str(exc),
                    "workload_started": False}
        with tempfile.TemporaryDirectory(prefix="foundry-seatbelt-") as directory:
            profile_path = Path(directory) / "profile.sb"
            profile_path.write_text(profile, encoding="utf-8")
            argv = [str(self.executable), "-f", str(profile_path), *[str(value) for value in command.argv]]
            before_dispatch()
            try:
                observed = subprocess.run(
                    argv, cwd=str(command.cwd), input=stdin, text=True,
                    capture_output=True, timeout=command.timeout_seconds,
                    env=dict(command.environment) if command.environment else None,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                        "reason_code": "SANDBOX_TIMEOUT", "workload_started": True,
                        "diagnostic": str(exc)}
            except (OSError, subprocess.SubprocessError) as exc:
                return {"status": "VALIDATION_FAILED", "provider_id": self.provider_id,
                        "reason_code": SANDBOX_UNAVAILABLE, "workload_started": True,
                        "diagnostic": str(exc)}
        return {
            "status": "PASS" if observed.returncode == 0 else "FAIL",
            "provider_id": self.provider_id,
            "sandbox_enforcement": "SEATBELT",
            "network_mode": "NONE",
            "exit_code": observed.returncode,
            "stdout": observed.stdout,
            "stderr": observed.stderr,
            "workload_started": True,
            "workpack_accepted": False,
        }
