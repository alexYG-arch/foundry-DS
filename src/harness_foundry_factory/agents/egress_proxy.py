"""Minimal host-local HTTP/CONNECT allowlist proxy for agent egress.

It binds loopback, accepts CONNECT tunnels and absolute-form HTTP requests, and
refuses hosts outside the explicit allowlist. It is a transport guard, not a
TLS-inspecting firewall and not an authorization system.
"""

from __future__ import annotations

import select
import socket
import socketserver
import threading
import urllib.parse


class _Handler(socketserver.StreamRequestHandler):
    def _deny(self):
        self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        self.wfile.flush()
        self.server.blocked.append(self._request_line)

    def handle(self):
        request_line = self.rfile.readline(65536).decode("latin-1").rstrip("\r\n")
        self._request_line = request_line
        if not request_line:
            return
        parts = request_line.split()
        if len(parts) < 3:
            self._deny(); return
        method, target, version = parts[0], parts[1], parts[2]
        headers = {}
        while True:
            line = self.rfile.readline(65536)
            if line in (b"\r\n", b"\n", b""):
                break
            key, _, value = line.decode("latin-1").partition(":")
            if key:
                headers[key.strip()] = value.strip()
        if method.upper() == "CONNECT":
            host, _, port = target.partition(":")
            port = int(port or "443")
            if host not in self.server.allowed_hosts:
                self._deny(); return
            try:
                upstream = socket.create_connection((host, port), timeout=30)
            except OSError:
                self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"); self.wfile.flush(); return
            self.server.connections.append(f"{host}:{port}")
            self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n"); self.wfile.flush()
            sockets = [self.connection, upstream]
            try:
                while True:
                    readable, _, _ = select.select(sockets, [], [], 60)
                    if not readable:
                        break
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is self.connection else self.connection).sendall(data)
            finally:
                upstream.close()
            return
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.hostname not in self.server.allowed_hosts:
            self._deny(); return
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if parsed.scheme == "https":
            # Only CONNECT is supported for HTTPS; absolute-form HTTPS is refused.
            self._deny(); return
        import http.client
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=30)
        body = b""
        length = 0
        for key, value in headers.items():
            if key.lower() == "content-length":
                length = int(value)
        if length:
            body = self.rfile.read(length)
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        forwarded = {key: value for key, value in headers.items() if key.lower() not in {"proxy-connection", "connection"}}
        try:
            connection.request(method, path, body=body, headers=forwarded)
            response = connection.getresponse()
            data = response.read()
            self.server.connections.append(f"{parsed.hostname}:{port}")
            self.wfile.write(f"HTTP/1.1 {response.status} {response.reason}\r\n".encode("latin-1"))
            for key, value in response.getheaders():
                if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                    self.wfile.write(f"{key}: {value}\r\n".encode("latin-1"))
            self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode("latin-1"))
            self.wfile.write(data); self.wfile.flush()
        except OSError:
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"); self.wfile.flush()
        finally:
            connection.close()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class AllowlistProxy:
    def __init__(self, allowed_hosts):
        self.allowed_hosts = frozenset(allowed_hosts)
        if not self.allowed_hosts:
            raise ValueError("allowed_hosts must be nonempty")
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.allowed_hosts = self.allowed_hosts
        self._server.connections = []
        self._server.blocked = []
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def proxy_url(self):
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def connections(self):
        return list(self._server.connections)

    @property
    def blocked(self):
        return list(self._server.blocked)

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
