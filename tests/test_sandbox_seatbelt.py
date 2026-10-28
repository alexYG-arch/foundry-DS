"""Seatbelt provider tests; real macOS sandbox, no model."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness_foundry_factory.agents.sandbox_seatbelt import SeatbeltSandboxProvider

SANDBOX = Path("/usr/bin/sandbox-exec")


@unittest.skipUnless(SANDBOX.is_file() and os.access(SANDBOX, os.X_OK), "seatbelt unavailable")
class SeatbeltProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve() / "workspace"
        self.workspace.mkdir()
        self.outside = Path(self.temp.name).resolve() / "outside.txt"
        self.provider = SeatbeltSandboxProvider()

    def command(self, argv, *, network=None):
        return SimpleNamespace(argv=argv, cwd=self.workspace, read_roots=[self.workspace],
                               write_roots=[self.workspace], timeout_seconds=15,
                               environment={}, network=network)

    def test_probe_passes(self):
        result = self.provider.probe()
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["sandbox_enforcement"], "SEATBELT")

    def test_echo_is_captured(self):
        result = self.provider.run(self.command(["/bin/echo", "hello"]), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["stdout"].strip(), "hello")
        self.assertFalse(result["workpack_accepted"])

    def test_write_inside_is_allowed_outside_is_denied(self):
        inside = self.workspace / "inside.txt"
        allowed = self.provider.run(self.command(["/usr/bin/touch", str(inside)]), before_dispatch=lambda: None)
        self.assertEqual(allowed["status"], "PASS", allowed)
        self.assertTrue(inside.exists())
        denied = self.provider.run(self.command(["/usr/bin/touch", str(self.outside)]), before_dispatch=lambda: None)
        self.assertEqual(denied["status"], "FAIL", denied)
        self.assertFalse(self.outside.exists())

    def test_read_outside_roots_is_denied(self):
        secret = Path(self.temp.name).resolve() / "secret.txt"
        secret.write_text("TOP_SECRET", encoding="utf-8")
        result = self.provider.run(self.command(["/bin/cat", str(secret)]), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "FAIL", result)
        self.assertNotIn("TOP_SECRET", result.get("stdout", ""))

    def test_remote_network_is_rejected(self):
        result = self.provider.run(self.command(["/bin/echo", "x"], network={"mode": "REMOTE_SERVICE"}),
                                   before_dispatch=lambda: None)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "SANDBOX_NETWORK_UNSUPPORTED")

    def test_missing_sandbox_exec_fails_closed(self):
        result = SeatbeltSandboxProvider(executable="/nonexistent/sandbox-exec").probe()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason_code"], "SANDBOX_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
