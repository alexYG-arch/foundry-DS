"""DeepSeek API adapter: local fake HTTP server, tool loop, no external model."""

from __future__ import annotations

import json
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from harness_foundry_factory.agents.api import DeepseekApiAdapter
from harness_foundry_factory.agents.base import AgentRequest
from harness_foundry_factory.agents.sandbox_seatbelt import SeatbeltSandboxProvider


class Handler(BaseHTTPRequestHandler):
    responses = []
    seen = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.seen.append(json.loads(self.rfile.read(length) or b"{}"))
        body = self.responses.pop(0)
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args):
        return


class ApiAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.key = self.root / "deepseek.key"
        self.key.write_text("fake-api-key\n")
        self.key.chmod(0o600)
        Handler.responses = [
            {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "call-1", "type": "function", "function": {
                    "name": "write_file", "arguments": json.dumps({"path": "proof.txt", "content": "API_OK"})}}]}}],
             "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
            {"choices": [{"message": {"content": "API_DONE"}}],
             "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        ]
        Handler.seen = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        def cleanup_server():
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(2)
        self.addCleanup(cleanup_server)

    def adapter(self, *, key_file=None):
        return DeepseekApiAdapter(base_url=f"http://127.0.0.1:{self.server.server_port}/v1",
                                  model="deepseek-chat", key_file=key_file or self.key,
                                  provider=SeatbeltSandboxProvider(), allow_insecure_localhost=True,
                                  timeout_seconds=10)

    def request(self):
        scope = SimpleNamespace(cwd=self.workspace, read_roots=[self.workspace], write_roots=[self.workspace])
        return AgentRequest(command=SimpleNamespace(scope=scope), prompt="write proof")

    def test_tool_loop_writes_file_and_returns_usage(self):
        result = self.adapter().run(self.request(), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["final_text"], "API_DONE")
        self.assertEqual((self.workspace / "proof.txt").read_text(), "API_OK")
        self.assertEqual(result["usage"]["total_tokens"], 7)
        self.assertEqual(result["event_types"], ["tool_call", "tool_result", "final"])
        self.assertNotIn("fake-api-key", json.dumps(result))
        self.assertEqual(len(Handler.seen), 2)

    def test_missing_key_does_not_dispatch(self):
        result = self.adapter(key_file=self.root / "absent.key").run(self.request(), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "BLOCKED_CREDENTIAL")
        self.assertFalse(result["workload_started"])

    def test_insecure_key_file_is_rejected(self):
        self.key.chmod(0o644)
        result = self.adapter().run(self.request(), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "BLOCKED_CREDENTIAL")


if __name__ == "__main__":
    unittest.main()
