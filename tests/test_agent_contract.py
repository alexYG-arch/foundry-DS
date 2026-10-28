"""Agent contract seam tests; no real Codex, model or target execution."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness_foundry_factory.agent_contract import (
    ADAPTER_PROBE_FAILED,
    SANDBOX_UNAVAILABLE,
    AgentCapabilities,
    AgentRequest,
)
from harness_foundry_factory.agent_codex import CodexCliAdapter, CodexSandboxProvider


class AgentContractTests(unittest.TestCase):
    def test_capabilities_reject_unknown_values(self):
        with self.assertRaises(ValueError):
            AgentCapabilities("x", "1", "socket", "jsonl", "REPORTED", "READABLE", False, "PROVIDER").validate()
        with self.assertRaises(ValueError):
            AgentCapabilities("x", "1", "stdin", "jsonl", "REPORTED", "READABLE", False, "UNKNOWN").validate()
        CodexCliAdapter.capabilities.validate()

    def test_probe_rejects_missing_or_relative_executable(self):
        result = CodexCliAdapter("/nonexistent/codex").probe()
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason_code"], ADAPTER_PROBE_FAILED)
        self.assertEqual(CodexSandboxProvider("/nonexistent/codex").probe()["reason_code"], SANDBOX_UNAVAILABLE)

    def test_probe_checks_required_exec_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "fake-codex"
            executable.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = exec ] && [ \"$2\" = --help ]; then\n"
                "  echo '--ignore-user-config --strict-config --ephemeral --json --cd stdin'\n"
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            result = CodexCliAdapter(executable).probe()
            self.assertEqual(result["status"], "PASS", result)
            self.assertTrue(result["interface_checked"])
            self.assertEqual(result["missing_flags"], [])
            self.assertEqual(result["adapter_id"], "codex-cli")

    def test_codex_adapter_delegates_to_existing_runner(self):
        request = AgentRequest(command=object(), prompt="p")
        before = lambda: None
        with mock.patch("harness_foundry_factory.coding_process.CodexCodingRunner") as runner:
            runner.return_value.run.return_value = {"status": "PASS"}
            result = CodexCliAdapter("/bin/echo").run(request, before_dispatch=before, observation=None)
        self.assertEqual(result, {"status": "PASS"})
        runner.assert_called_once_with(Path("/bin/echo"))
        runner.return_value.run.assert_called_once_with(request.command, before_dispatch=before, observation=None)

    def test_codex_sandbox_provider_delegates_to_existing_runner(self):
        command = object()
        before = lambda: None
        with mock.patch("harness_foundry_factory.local_process.CodexSandboxRunner") as runner:
            runner.return_value.run.return_value = {"status": "PASS"}
            result = CodexSandboxProvider("/bin/echo").run(command, before_dispatch=before, observation=None)
        self.assertEqual(result, {"status": "PASS"})
        runner.assert_called_once_with(Path("/bin/echo"))
        runner.return_value.run.assert_called_once_with(command, before_dispatch=before, observation=None)


if __name__ == "__main__":
    unittest.main()
