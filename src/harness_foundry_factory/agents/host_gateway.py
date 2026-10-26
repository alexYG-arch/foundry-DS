"""Host-local OpenAI-compatible gateway that keeps the model key off the guest.

The guest holds only a random gateway token. The gateway strips that token,
adds the real key, and forwards only the declared chat-completions path.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _Handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path not in {"/v1/chat/completions", "/chat/completions"}:
            self._send(404, {"error": "unsupported path"}); return
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer " + self.server.gateway_token:
            self._send(401, {"error": "gateway token required"}); return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"}); return
        request = urllib.request.Request(
            self.server.upstream + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
            method="POST", headers={"Content-Type": "application/json",
                                    "Authorization": "Bearer " + self.server.api_key})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._send(exc.code, {"error": "upstream HTTP error"})
        except (urllib.error.URLError, TimeoutError):
            self._send(502, {"error": "upstream unavailable"})

    def log_message(self, *args):
        return


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class HostApiGateway:
    def __init__(self, *, upstream="https://api.deepseek.com", api_key=None, key_file=None,
                 bind="0.0.0.0", token=None):
        self.upstream = upstream.rstrip("/")
        self.bind = bind
        self.token = token or secrets.token_urlsafe(32)
        if api_key is None:
            value = os.environ.get("DEEPSEEK_API_KEY")
            if not value:
                path = Path(key_file) if key_file is not None else Path.home() / ".dsh/foundry/deepseek.key"
                if not path.exists() or stat.S_IMODE(path.stat().st_mode) & 0o077:
                    raise ValueError("host API key is unavailable or not 0600")
                value = path.read_text(encoding="utf-8").strip()
            api_key = value
        if not api_key:
            raise ValueError("host API key is empty")
        self._api_key = api_key
        self._server = _Server((bind, 0), _Handler)
        self._server.api_key = api_key
        self._server.gateway_token = self.token
        self._server.upstream = self.upstream
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self):
        return self._server.server_address[1]

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(2)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
