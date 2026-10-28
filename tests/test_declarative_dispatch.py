"""M2.1a fixture dispatch: profile + NoneSandboxProvider, no model."""

from __future__ import annotations

import json
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness_foundry_factory.agents.base import AgentRequest
from harness_foundry_factory.agents.profile import DeclarativeAdapter, DeclarativeProfile
from harness_foundry_factory.agents.sandbox_none import NoneSandboxProvider

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "tests/fixtures/agents/fixture-profile.json"
AGENT = ROOT / "tests/fixtures/agents/fixture-agent.sh"


class DeclarativeDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.agent = self.workspace / "fixture-agent"
        shutil.copy2(AGENT, self.agent)
        self.agent.chmod(self.agent.stat().st_mode | stat.S_IXUSR)
        self.profile = DeclarativeProfile.load(PROFILE)

    def request(self):
        scope = SimpleNamespace(cwd=self.workspace, read_roots=[self.workspace],
                                write_roots=[self.workspace], timeout_seconds=30, environment={})
        return AgentRequest(command=SimpleNamespace(scope=scope), prompt="hello")

    def test_fixture_run_writes_declared_outputs(self):
        adapter = DeclarativeAdapter(self.profile, executable=self.agent,
                                     provider=NoneSandboxProvider(allow_unsandboxed_agent=True))
        result = adapter.run(self.request(), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["sandbox_enforcement"], "NONE")
        self.assertEqual((self.workspace / "src/reader.py").read_text(), "VALUE = 'fixture'\n")
        self.assertEqual(json.loads((self.workspace / "outputs/summary.json").read_text()), {"fixture": True})
        self.assertFalse(result["workpack_accepted"])

    def test_no_provider_never_dispatches(self):
        adapter = DeclarativeAdapter(self.profile, executable=self.agent)
        with self.assertRaises(NotImplementedError):
            adapter.run(self.request(), before_dispatch=lambda: None)

    def test_none_provider_requires_explicit_allow(self):
        provider = NoneSandboxProvider(allow_unsandboxed_agent=False)
        result = provider.run(SimpleNamespace(argv=["/bin/true"], cwd=self.workspace,
                                              timeout_seconds=5, environment={},
                                              network=None), before_dispatch=lambda: None)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "SANDBOX_UNAVAILABLE")
        self.assertFalse(result["workload_started"])

    def test_none_provider_rejects_network(self):
        provider = NoneSandboxProvider(allow_unsandboxed_agent=True)
        result = provider.run(SimpleNamespace(argv=["/bin/true"], cwd=self.workspace,
                                              timeout_seconds=5, environment={},
                                              network={"mode": "REMOTE_SERVICE"}),
                              before_dispatch=lambda: None)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["reason_code"], "SANDBOX_NETWORK_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
