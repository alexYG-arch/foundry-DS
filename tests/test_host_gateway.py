"""Host API gateway tests with a local fake upstream; no real key/network."""

from __future__ import annotations

import http.server
import json
import threading
import unittest
import urllib.error
import urllib.request

from harness_foundry_factory.agents.host_gateway import HostApiGateway


class Upstream(http.server.BaseHTTPRequestHandler):
    seen = []
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        Upstream.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        data = json.dumps({"choices": [{"message": {"content": "GATEWAY_OK"}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *args):
        return


class HostGatewayTests(unittest.TestCase):
    def setUp(self):
        self.upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.thread = threading.Thread(target=self.upstream.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.upstream.server_close); self.addCleanup(self.upstream.shutdown); self.addCleanup(self.thread.join, 2)
        Upstream.seen = []
        self.gateway = HostApiGateway(upstream=f"http://127.0.0.1:{self.upstream.server_address[1]}",
                                      api_key="real-host-key", bind="127.0.0.1").start()
        self.addCleanup(self.gateway.stop)

    def post(self, token):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.gateway.port}/v1/chat/completions",
            data=json.dumps({"model": "x", "messages": []}).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        return urllib.request.urlopen(request, timeout=10)

    def test_token_is_replaced_with_host_key(self):
        with self.post(self.gateway.token) as response:
            self.assertEqual(json.loads(response.read())["choices"][0]["message"]["content"], "GATEWAY_OK")
        self.assertEqual(Upstream.seen[-1]["auth"], "Bearer real-host-key")
        self.assertEqual(Upstream.seen[-1]["path"], "/chat/completions")

    def test_wrong_token_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("wrong")
        self.assertEqual(caught.exception.code, 401)
        self.assertEqual(Upstream.seen, [])


if __name__ == "__main__":
    unittest.main()
