"""DSH headless adapter tests with a local test double (no model/API)."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness_foundry_factory.agents.base import AgentRequest
from harness_foundry_factory.agents.dsh import BLOCKED_CREDENTIAL, DshHeadlessAdapter

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests/fixtures/agents/fake-dsh.sh"


class DshHeadlessAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.dsh = self.workspace / "dsh"
        self.dsh.write_text(FAKE.read_text())
        self.dsh.chmod(self.dsh.stat().st_mode | stat.S_IXUSR)
        self.dsh_home = self.root / "dsh-home"
        self.dsh_home.mkdir()
        self.key_file = self.root / "deepseek.key"
        self.key_file.write_text("fake-key-not-real\n")
        self.key_file.chmod(0o600)

    def request(self):
        scope = SimpleNamespace(cwd=self.workspace)
        return AgentRequest(command=SimpleNamespace(scope=scope), prompt="hello")

    def adapter(self, **kwargs):
        return DshHeadlessAdapter(self.dsh, self.dsh_home, key_file=self.key_file,
                                  timeout_seconds=15, **kwargs)

    def test_probe_and_file_credential_run(self):
        adapter = self.adapter()
        self.assertEqual(adapter.probe()["status"], "PASS")
        called = []
        result = adapter.run(self.request(), before_dispatch=lambda: called.append(True))
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["final_text"], "DONE")
        self.assertEqual(result["session_id"], "session-fake")
        self.assertEqual(result["credential_source"], "FILE")
        self.assertTrue(result["workload_started"])
        self.assertFalse(result["workpack_accepted"])
        self.assertEqual(called, [True])
        self.assertNotIn("fake-key-not-real", json.dumps(result))

    def test_missing_key_does_not_dispatch(self):
        adapter = DshHeadlessAdapter(self.dsh, self.dsh_home, key_file=self.root / "absent.key")
        called = []
        result = adapter.run(self.request(), before_dispatch=lambda: called.append(True))
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], BLOCKED_CREDENTIAL)
        self.assertFalse(result["workload_started"])
        self.assertEqual(called, [])

    def test_insecure_key_file_is_rejected(self):
        self.key_file.chmod(0o644)
        adapter = self.adapter()
        result = adapter.run(self.request(), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], BLOCKED_CREDENTIAL)
        self.assertFalse(result["workload_started"])

    def test_proxy_environment_is_injected(self):
        adapter = DshHeadlessAdapter(self.dsh, self.dsh_home, key_file=self.key_file,
                                     proxy_url="http://127.0.0.1:12345")
        env = adapter._environment("fake-key")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:12345")
        self.assertEqual(env["NODE_USE_ENV_PROXY"], "1")
        self.assertNotIn("NO_PROXY", env)

    def test_environment_key_is_supported(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "fake-env-key"}, clear=False):
            adapter = DshHeadlessAdapter(self.dsh, self.dsh_home, key_file=self.root / "absent.key")
            result = adapter.run(self.request(), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["credential_source"], "ENV")
        self.assertNotIn("fake-env-key", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
