"""Host-local allowlist proxy tests; no external network."""

from __future__ import annotations

import http.server
import json
import threading
import unittest
from urllib.request import ProxyHandler, build_opener

from harness_foundry_factory.agents.egress_proxy import AllowlistProxy


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        body = json.dumps({"ok": True, "path": self.path, "size": len(data)}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *args):
        return


class EgressProxyTests(unittest.TestCase):
    def setUp(self):
        self.target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.target.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.target.server_close); self.addCleanup(self.target.shutdown); self.addCleanup(self.thread.join, 2)
        self.proxy = AllowlistProxy({"127.0.0.1"}).start()
        self.addCleanup(self.proxy.stop)

    def test_http_request_is_forwarded_and_counted(self):
        import socket
        port = self.target.server_address[1]
        with socket.create_connection(("127.0.0.1", int(self.proxy.proxy_url.rsplit(":", 1)[1])), timeout=10) as sock:
            body = b"hello"
            request = (f"POST http://127.0.0.1:{port}/v1/check HTTP/1.1\r\n"
                       f"Host: 127.0.0.1:{port}\r\nContent-Length: {len(body)}\r\n"
                       "Content-Type: application/json\r\n\r\n").encode() + body
            sock.sendall(request)
            response = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                response += chunk
        self.assertIn(b"200", response.split(b"\r\n", 1)[0])
        self.assertIn(b'"ok": true', response)
        self.assertTrue(any(item.startswith("127.0.0.1:") for item in self.proxy.connections))

    def test_connect_tunnel_is_forwarded(self):
        import socket, socketserver, threading
        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                while data := self.request.recv(65536):
                    self.request.sendall(data)
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown); self.addCleanup(thread.join, 2)
        proxy_host, proxy_port = self.proxy.proxy_url.rsplit("://", 1)[1].rsplit(":", 1)
        with socket.create_connection((proxy_host, int(proxy_port)), timeout=10) as sock:
            sock.sendall(f"CONNECT 127.0.0.1:{server.server_address[1]} HTTP/1.1\r\n\r\n".encode())
            head = sock.recv(1024)
            self.assertIn(b"200", head)
            sock.sendall(b"CONNECT_OK")
            self.assertEqual(sock.recv(1024), b"CONNECT_OK")
        self.assertTrue(any(item.startswith("127.0.0.1:") for item in self.proxy.connections))

    def test_disallowed_host_is_denied(self):
        import socket
        proxy_host, proxy_port = self.proxy.proxy_url.rsplit("://", 1)[1].rsplit(":", 1)
        with socket.create_connection((proxy_host, int(proxy_port)), timeout=10) as sock:
            sock.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
            response = sock.recv(1024)
        self.assertTrue(response.startswith(b"HTTP/1.1 403"), response)
        self.assertTrue(self.proxy.blocked)


if __name__ == "__main__":
    unittest.main()
