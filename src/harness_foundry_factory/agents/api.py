"""DeepSeek OpenAI-compatible API transport with a constrained tool loop."""

from __future__ import annotations

import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .base import ADAPTER_PROBE_FAILED, AgentCapabilities, AgentRequest
from .sandbox_seatbelt import SeatbeltSandboxProvider

BLOCKED_CREDENTIAL = "BLOCKED_CREDENTIAL"
API_TOOL_LOOP_LIMIT = "API_TOOL_LOOP_LIMIT"


class DeepseekApiAdapter:
    """A small, explicitly constrained controller-side tool loop.

    The model never gets a shell. Every file/tool operation is checked against
    the request scope; command execution goes through a SandboxProvider.
    """

    def __init__(self, *, base_url, model, key_file=None, provider=None,
                 timeout_seconds=120, max_turns=8, allow_insecure_localhost=False):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("plain HTTP is only allowed for localhost")
        if parsed.scheme != "https" and not allow_insecure_localhost:
            # Explicit opt-in keeps the default honest even for localhost.
            raise ValueError("allow_insecure_localhost must be true for local HTTP")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.key_file = Path(key_file) if key_file is not None else Path.home() / ".dsh/foundry/deepseek.key"
        self.provider = provider or SeatbeltSandboxProvider()
        self.timeout_seconds = timeout_seconds
        self.max_turns = max_turns
        self.capabilities = AgentCapabilities(
            adapter_id="deepseek-api", adapter_version="1", prompt_transport="http",
            events="jsonl", usage="UNKNOWN", defaults="EXPLICIT_ONLY",
            handoff=False, sandbox="PROVIDER",
        )
        self.capabilities.validate()

    def _credential(self):
        value = os.environ.get("DEEPSEEK_API_KEY")
        if isinstance(value, str) and value.strip():
            return value.strip(), "ENV"
        if not self.key_file.exists():
            return None, "NONE"
        if stat.S_IMODE(self.key_file.stat().st_mode) & 0o077:
            raise PermissionError("key file must be chmod 600")
        value = self.key_file.read_text(encoding="utf-8").strip()
        return (value, "FILE") if value else (None, "NONE")

    def probe(self):
        try:
            key, source = self._credential()
        except PermissionError as exc:
            return {"status": "FAIL", "adapter_id": "deepseek-api",
                    "reason_code": BLOCKED_CREDENTIAL, "diagnostic": str(exc)}
        return {"status": "PASS" if key else "FAIL", "adapter_id": "deepseek-api",
                "reason_code": None if key else BLOCKED_CREDENTIAL,
                "credential_source": source, "base_url": self.base_url}

    def _post(self, payload, key):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/chat/completions", data=data, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            code = "API_AUTH_FAILED" if exc.code in {401, 403} else "API_HTTP_ERROR"
            raise RuntimeError(f"{code}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"API_NETWORK_ERROR: {exc}") from exc
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("API_SCHEMA_UNSUPPORTED: response is not JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("choices"), list) or not value["choices"]:
            raise RuntimeError("API_SCHEMA_UNSUPPORTED: missing choices")
        return value

    @staticmethod
    def _tools():
        return [
            {"type": "function", "function": {"name": "read_file", "description": "Read a bounded text file.",
              "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "list_dir", "description": "List a directory.",
              "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "write_file", "description": "Write a text file inside the workspace.",
              "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                             "required": ["path", "content"]}}},
            {"type": "function", "function": {"name": "run_command", "description": "Run argv under the sandbox; no shell.",
              "parameters": {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}},
                             "cwd": {"type": "string"}, "timeout_seconds": {"type": "number"}},
                             "required": ["argv"]}}},
        ]

    def _path(self, value, roots, base, *, must_exist=True):
        if not isinstance(value, str) or not value:
            raise ValueError("path must be nonempty text")
        path = Path(value)
        if not path.is_absolute():
            path = Path(base) / path
        path = path.resolve()
        if not any(path == root or path.is_relative_to(root) for root in roots):
            raise ValueError("path is outside the declared roots")
        if must_exist and not path.exists():
            raise ValueError("path does not exist")
        return path

    def _execute(self, call, scope):
        name = call.get("name")
        try:
            args = json.loads(call.get("arguments", "{}"))
        except json.JSONDecodeError:
            return {"status": "ERROR", "error": "arguments are not JSON"}
        if not isinstance(args, dict):
            return {"status": "ERROR", "error": "arguments must be an object"}
        workspace = Path(scope.cwd).resolve()
        reads = [workspace, *[Path(root).resolve() for root in getattr(scope, "read_roots", ())]]
        writes = [Path(root).resolve() for root in getattr(scope, "write_roots", (workspace,))]
        try:
            if name == "read_file":
                path = self._path(args.get("path"), reads, workspace)
                return {"status": "OK", "content": path.read_text(encoding="utf-8")[:65536]}
            if name == "list_dir":
                path = self._path(args.get("path"), reads, workspace)
                if not path.is_dir():
                    raise ValueError("not a directory")
                return {"status": "OK", "entries": sorted(item.name for item in path.iterdir())[:500]}
            if name == "write_file":
                path = self._path(args.get("path"), writes, workspace, must_exist=False)
                path.parent.mkdir(parents=True, exist_ok=True)
                content = args.get("content")
                if not isinstance(content, str):
                    raise ValueError("content must be text")
                path.write_text(content, encoding="utf-8")
                return {"status": "OK", "path": str(path), "bytes": len(content.encode("utf-8"))}
            if name == "run_command":
                argv = args.get("argv")
                if not isinstance(argv, list) or not argv or any(not isinstance(item, str) for item in argv):
                    raise ValueError("argv must be a nonempty string list")
                cwd = self._path(args.get("cwd", str(workspace)), reads, workspace)
                if not cwd.is_dir():
                    raise ValueError("cwd is not a directory")
                timeout = args.get("timeout_seconds", self.timeout_seconds)
                if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 3600:
                    raise ValueError("timeout_seconds must be positive and <= 3600")
                command = type("Command", (), {"argv": argv, "cwd": cwd, "read_roots": reads,
                                                "write_roots": writes, "timeout_seconds": timeout,
                                                "environment": {}, "network": None})()
                result = self.provider.run(command, before_dispatch=lambda: None)
                return {"status": result.get("status"), "exit_code": result.get("exit_code"),
                        "stdout": (result.get("stdout") or "")[:65536],
                        "stderr": (result.get("stderr") or "")[:16384]}
            return {"status": "ERROR", "error": f"unsupported tool: {name}"}
        except (OSError, ValueError) as exc:
            return {"status": "ERROR", "error": str(exc)}

    def run(self, request: AgentRequest, *, before_dispatch, **hooks):
        try:
            key, source = self._credential()
        except PermissionError as exc:
            return {"status": "VALIDATION_FAILED", "adapter_id": "deepseek-api",
                    "reason_code": BLOCKED_CREDENTIAL, "workload_started": False, "diagnostic": str(exc)}
        if key is None:
            return {"status": "VALIDATION_FAILED", "adapter_id": "deepseek-api",
                    "reason_code": BLOCKED_CREDENTIAL, "workload_started": False}
        scope = getattr(request.command, "scope", request.command)
        messages = [
            {"role": "system", "content": "You are a constrained implementation agent. Use tools to edit the workspace. "
                                          "Do not claim acceptance."},
            {"role": "user", "content": request.prompt},
        ]
        events = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        before_dispatch()
        for turn in range(self.max_turns):
            try:
                response = self._post({"model": self.model, "messages": messages, "tools": self._tools(),
                                       "tool_choice": "auto", "temperature": 0}, key)
            except RuntimeError as exc:
                return {"status": "FAIL", "adapter_id": "deepseek-api", "reason_code": str(exc).split(":", 1)[0],
                        "workload_started": True, "credential_source": source, "sandbox_enforcement": "PROVIDER",
                        "workpack_accepted": False, "event_types": [event.get("type") for event in events]}
            for key_name in usage:
                usage[key_name] += int((response.get("usage") or {}).get(key_name, 0) or 0)
            message = response["choices"][0].get("message") or {}
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                final = message.get("content") or ""
                events.append({"type": "final", "text": final})
                return {"status": "PASS" if final.strip() else "FAIL", "adapter_id": "deepseek-api",
                        "adapter_version": "1", "reason_code": None, "final_text": final,
                        "event_types": [event.get("type") for event in events], "event_count": len(events),
                        "usage": usage, "credential_source": source, "sandbox_enforcement": "PROVIDER",
                        "workload_started": True, "workpack_accepted": False}
            messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": tool_calls})
            for call in tool_calls:
                function = call.get("function") or {}
                events.append({"type": "tool_call", "name": function.get("name")})
                result = self._execute({"name": function.get("name"), "arguments": function.get("arguments", "{}")}, scope)
                events.append({"type": "tool_result", "name": function.get("name"), "status": result.get("status")})
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "content": json.dumps(result, ensure_ascii=False)})
        return {"status": "FAIL", "adapter_id": "deepseek-api", "reason_code": API_TOOL_LOOP_LIMIT,
                "workload_started": True, "credential_source": source, "sandbox_enforcement": "PROVIDER",
                "workpack_accepted": False, "event_types": [event.get("type") for event in events], "usage": usage}
