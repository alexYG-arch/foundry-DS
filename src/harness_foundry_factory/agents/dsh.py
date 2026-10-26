"""DSH headless adapter (P2 transport, no model calls in tests).

Credentials are resolved just-in-time from ``DEEPSEEK_API_KEY`` or a 0600 local
key file. The key is never stored in a Scope, result, or log.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from .base import ADAPTER_PROBE_FAILED, AgentCapabilities, AgentRequest

BLOCKED_CREDENTIAL = "BLOCKED_CREDENTIAL"


class DshHeadlessAdapter:
    """Drive ``dsh --profile headless --json`` and retain its raw events."""

    def __init__(self, executable, dsh_home, *, key_file=None, timeout_seconds=1800,
                 session_id=None, proxy_url=None):
        self.executable = Path(executable)
        self.dsh_home = Path(dsh_home)
        self.key_file = Path(key_file) if key_file is not None else self.dsh_home / "foundry" / "deepseek.key"
        self.timeout_seconds = timeout_seconds
        if session_id is not None:
            if not isinstance(session_id, str) or not session_id.strip() or any(c in session_id for c in "\x00\r\n"):
                raise ValueError("session_id must be nonempty text without NUL/newlines")
        self.session_id = session_id
        self.proxy_url = proxy_url
        self.capabilities = AgentCapabilities(
            adapter_id="dsh-headless", adapter_version="1", prompt_transport="stdin",
            events="jsonl", usage="UNKNOWN", defaults="EXPLICIT_ONLY",
            handoff=True, sandbox="NATIVE",
        )
        self.capabilities.validate()

    def _credential(self):
        value = os.environ.get("DEEPSEEK_API_KEY")
        if isinstance(value, str) and value.strip():
            return value.strip(), "ENV"
        if not self.key_file.exists():
            return None, "NONE"
        mode = stat.S_IMODE(self.key_file.stat().st_mode)
        if mode & 0o077:
            raise PermissionError("key file must not be group/world accessible (use chmod 600)")
        value = self.key_file.read_text(encoding="utf-8").strip()
        if not value:
            return None, "NONE"
        return value, "FILE"

    def probe(self, executable=None):
        path = Path(executable) if executable is not None else self.executable
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            return {"status": "FAIL", "adapter_id": "dsh-headless",
                    "reason_code": ADAPTER_PROBE_FAILED, "diagnostic": "executable is not executable"}
        try:
            observed = subprocess.run([str(path), "--version"], capture_output=True, text=True,
                                      timeout=15, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "FAIL", "adapter_id": "dsh-headless",
                    "reason_code": ADAPTER_PROBE_FAILED, "diagnostic": str(exc)}
        passed = observed.returncode == 0 and bool(observed.stdout.strip())
        return {"status": "PASS" if passed else "FAIL", "adapter_id": "dsh-headless",
                "reason_code": None if passed else ADAPTER_PROBE_FAILED,
                "version": observed.stdout.strip() if passed else None}

    def _environment(self, key):
        environment = dict(os.environ)
        environment["DSH_HOME"] = str(self.dsh_home)
        if key is not None:
            environment["DEEPSEEK_API_KEY"] = key
        if self.proxy_url:
            for name in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
                environment[name] = self.proxy_url
            environment["NODE_USE_ENV_PROXY"] = "1"
            environment.pop("NO_PROXY", None)
            environment.pop("no_proxy", None)
        return environment

    @staticmethod
    def _parse_events(stdout):
        events = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                events.append({"type": "UNKNOWN", "raw": line})
                continue
            events.append(value if isinstance(value, dict) else {"type": "UNKNOWN", "raw": line})
        return events

    def run(self, request: AgentRequest, *, before_dispatch, **hooks):
        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            return {"status": "FAIL", "adapter_id": "dsh-headless",
                    "reason_code": ADAPTER_PROBE_FAILED, "workload_started": False}
        try:
            key, source = self._credential()
        except PermissionError as exc:
            return {"status": "VALIDATION_FAILED", "adapter_id": "dsh-headless",
                    "reason_code": BLOCKED_CREDENTIAL, "diagnostic": str(exc),
                    "workload_started": False}
        if key is None:
            return {"status": "VALIDATION_FAILED", "adapter_id": "dsh-headless",
                    "reason_code": BLOCKED_CREDENTIAL,
                    "diagnostic": "DEEPSEEK_API_KEY or a 0600 key file is required",
                    "workload_started": False}
        scope = getattr(request.command, "scope", request.command)
        cwd = Path(getattr(scope, "cwd", "")).resolve()
        argv = [str(self.executable), "--profile", "headless", "--json"]
        if self.session_id is not None:
            argv.extend(["--session-id", self.session_id])
        argv.append("-")
        before_dispatch()
        try:
            observed = subprocess.run(
                argv, cwd=str(cwd), input=request.prompt, text=True,
                capture_output=True, timeout=self.timeout_seconds,
                env=self._environment(key), check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {"status": "VALIDATION_FAILED", "adapter_id": "dsh-headless",
                    "reason_code": "DSH_TIMEOUT", "workload_started": True,
                    "credential_source": source, "diagnostic": str(exc)}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "VALIDATION_FAILED", "adapter_id": "dsh-headless",
                    "reason_code": ADAPTER_PROBE_FAILED, "workload_started": True,
                    "credential_source": source, "diagnostic": str(exc)}
        events = self._parse_events(observed.stdout)
        session_id = next((event.get("sessionId") for event in events if event.get("type") == "session"), None)
        final_text = next((event.get("text", "") for event in events if event.get("type") == "final"), "")
        error = None
        for event in events:
            reason = event.get("reason") if event.get("type") == "status" else None
            if isinstance(reason, dict) and reason.get("kind") == "error":
                error = reason.get("error", {})
        reason_code = error.get("code") if isinstance(error, dict) else None
        status = "PASS" if observed.returncode == 0 and not error and bool(final_text.strip()) else "FAIL"
        return {
            "status": status,
            "adapter_id": "dsh-headless",
            "adapter_version": self.capabilities.adapter_version,
            "reason_code": BLOCKED_CREDENTIAL if reason_code == "MISSING_CREDENTIAL" else reason_code,
            "exit_code": observed.returncode,
            "session_id": session_id,
            "final_text": final_text,
            "event_types": [event.get("type") for event in events],
            "event_count": len(events),
            "usage": "UNKNOWN",
            "credential_source": source,
            "sandbox_enforcement": "NATIVE",
            "workload_started": True,
            "workpack_accepted": False,
        }
