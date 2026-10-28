"""Scope 1.3 + AGENT fixture under a real seatbelt sandbox (darwin gate set only).

This module is loaded by the public gate only on macOS; it is not skipped
elsewhere, it is simply not part of the Linux required set.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from harness_foundry_factory.agents.profile import DeclarativeAdapter
from harness_foundry_factory.agents.sandbox_seatbelt import SeatbeltSandboxProvider
from harness_foundry_factory.agents.scope13 import run_agent_workpack, validate_scope_13
from tests.test_agent_scope13 import AgentScope13Fixture

SEATBELT = sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file()


@unittest.skipUnless(SEATBELT, "seatbelt unavailable")
class AgentScope13SeatbeltTests(AgentScope13Fixture):
    provider_block = {"provider": "seatbelt", "network": {"agent_egress": "NONE", "task_network": "NONE"}}
    execution_block = {"mode": "SANDBOX"}

    def test_fixture_agent_runs_under_real_seatbelt(self):
        validate_scope_13(self.plan, self.scope)
        adapter = DeclarativeAdapter(self.profile, executable=self.agent, provider=SeatbeltSandboxProvider())
        result = run_agent_workpack(self.plan, self.scope, "IMPLEMENT", adapter=adapter,
                                    provider=SeatbeltSandboxProvider(), prompt="hello")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["sandbox_enforcement"], "SEATBELT")
        self.assertEqual(result["before_dispatch_calls"], 1)
        self.assertEqual((self.workspace / "src/reader.py").read_text(), "VALUE = 'fixture'\n")
        self.assertFalse(result["workpack_accepted"])


if __name__ == "__main__":
    unittest.main()
