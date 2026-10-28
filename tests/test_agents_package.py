"""M1.1 package layout and compatibility shim tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import harness_foundry_factory.agent_codex as shim_codex
import harness_foundry_factory.agent_contract as shim_contract
from harness_foundry_factory.agents import (
    AgentCapabilities,
    AgentRequest,
    CodexCliAdapter,
    CodexSandboxProvider,
)
from harness_foundry_factory.agents.base import AgentCapabilities as BaseCapabilities
from harness_foundry_factory.agents.codex import CodexCliAdapter as PackageCodexCliAdapter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("generic_packager", ROOT / "devtools/package_generic_release.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class AgentsPackageTests(unittest.TestCase):
    def test_package_exports_and_shims_are_identical(self):
        self.assertIs(AgentCapabilities, BaseCapabilities)
        self.assertIs(CodexCliAdapter, PackageCodexCliAdapter)
        self.assertIs(shim_contract.AgentCapabilities, AgentCapabilities)
        self.assertIs(shim_contract.AgentRequest, AgentRequest)
        self.assertIs(shim_codex.CodexCliAdapter, CodexCliAdapter)
        self.assertIs(shim_codex.CodexSandboxProvider, CodexSandboxProvider)

    def test_capabilities_still_validate(self):
        AgentCapabilities("codex-cli", "1", "stdin", "jsonl", "REPORTED", "READABLE", True, "PROVIDER").validate()
        with self.assertRaises(ValueError):
            AgentCapabilities("x", "1", "socket", "jsonl", "REPORTED", "READABLE", False, "PROVIDER").validate()

    def test_bubblewrap_argv_isolates_network_and_writes(self):
        from types import SimpleNamespace
        from harness_foundry_factory.agents.sandbox_bwrap import BubblewrapSandboxProvider
        provider = BubblewrapSandboxProvider(executable="/bin/true")
        argv = provider._argv(SimpleNamespace(argv=["/bin/echo", "ok"], cwd="/tmp",
                                              write_roots=["/tmp/allow"]))
        self.assertIn("--unshare-net", argv)
        self.assertIn("--die-with-parent", argv)
        resolved = str(Path("/tmp/allow").resolve())
        self.assertEqual(argv[argv.index("--bind"):argv.index("--bind") + 3], ["--bind", resolved, resolved])

    def test_release_package_contains_agents_package(self):
        result = packager.package(None)
        files = set(result["files"])
        for relative in ("agents/__init__.py", "agents/base.py", "agents/codex.py", "agents/profile.py", "agents/sandbox_none.py", "agents/sandbox_seatbelt.py", "agents/sandbox_bwrap.py", "agents/sandbox_trusted.py", "agents/scope13.py", "agents/dsh.py", "agents/api.py", "agents/agent_controller.py", "agents/egress_proxy.py", "agents/host_gateway.py", "agents/artifacts.py", "agents/verifier.py", "agents/limits.py", "agents/verifier_runner.py"):
            self.assertIn(f"src/harness_foundry_factory/{relative}", files)
        self.assertIn("src/harness_foundry_factory/agent_contract.py", files)
        self.assertIn("src/harness_foundry_factory/agent_codex.py", files)


if __name__ == "__main__":
    unittest.main()
