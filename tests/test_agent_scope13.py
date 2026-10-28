"""Scope 1.3 + AGENT fixture: no Codex, no model, platform-neutral provider.

The real seatbelt run lives in ``test_agent_scope13_seatbelt`` (darwin gate set).
"""

from __future__ import annotations

import json
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from harness_foundry_factory.agents.profile import DeclarativeAdapter, DeclarativeProfile
from harness_foundry_factory.agents.sandbox_trusted import TrustedHostProvider
from harness_foundry_factory.agents.scope13 import (
    agent_read_roots, run_agent_workpack, validate_scope_13, verifier_files,
)
from harness_foundry_factory.build_plan import compile_build_plan

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "tests/fixtures/agents/fixture-agent.sh"
PROFILE = ROOT / "tests/fixtures/agents/fixture-profile.json"


def requirement():
    return {
        "requirement_ir": {
            "program_id": "P1-AGENT-FIXTURE", "revision": 1,
            "target": {"id": "P1", "mission": "Exercise an AGENT workpack.", "scope": ["write reader"], "non_goals": []},
            "sources": [{"source_id": "BRIEF", "path_or_uri": "project://brief.md", "loaded_completely": True}],
            "atoms": [
                {"atom_id": "A1", "text_or_lossless_paraphrase": "Write the reader.", "source_id": "BRIEF", "source_locator": "#a1"},
                {"atom_id": "A2", "text_or_lossless_paraphrase": "Reject malformed input.", "source_id": "BRIEF", "source_locator": "#a2"},
            ],
            "acceptance_cases": [{"case_id": "C1", "atom_ids": ["A1"], "description": "Reader exists."}],
            "negative_cases": [{"case_id": "N1", "atom_ids": ["A2"], "description": "Malformed rejected."}],
        },
        "plan": {
            "schema_version": "1.3", "plan_id": "P1-PLAN", "revision": 1, "requirement_revision": 1,
            "workpacks": [{
                "workpack_id": "IMPLEMENT", "job_id": "IMPLEMENT", "executor": "AGENT",
                "agent": {"adapter": "fixture-agent", "adapter_version": "1"},
                "goal": "Write the reader.", "depends_on": [], "atom_ids": ["A1", "A2"],
                "inputs": [{"kind": "SOURCE", "id": "BRIEF"}],
                "artifacts": [{"artifact_id": "READER", "path": "src/reader.py"}],
                "verification": [
                    {"case_id": "C1", "argv": ["python", "verifier://check.py"], "artifact_ids": ["READER"]},
                    {"case_id": "N1", "argv": ["python", "verifier://check.py", "--negative"], "artifact_ids": ["READER"]},
                ],
            }],
        },
    }


class AgentScope13Fixture(unittest.TestCase):
    """Shared layout: agent binary outside the workspace, checker in its own root."""

    provider_block = {"provider": "none", "network": {"agent_egress": "NONE", "task_network": "NONE"}}
    execution_block = {"mode": "TRUSTED_HOST"}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.verifier = self.root / "verifier"
        self.verifier.mkdir()
        (self.verifier / "check.py").write_text("print('ok')\n")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        self.agent = bin_dir / "fixture-agent"
        shutil.copy2(AGENT, self.agent)
        self.agent.chmod(self.agent.stat().st_mode | stat.S_IXUSR)
        raw = json.loads(PROFILE.read_text())
        raw["capabilities"]["sandbox"] = "PROVIDER"
        self.profile = DeclarativeProfile.from_dict(raw)
        self.plan = requirement()["plan"]
        self.scope = {
            "scope_version": "1.3",
            "agents": {"fixture": {"adapter": "fixture-agent", "executable": str(self.agent)}},
            "sandbox": dict(self.provider_block),
            "usage_accounting": "ADAPTER_REPORTED",
            "workspace_root": str(self.workspace),
            "source_read_roots": [str(self.workspace)],
            "verification_root": str(self.verifier),
            "task_write_roots": {"IMPLEMENT": [str(self.workspace)]},
            "executables": {"python": sys.executable},
            "max_attempts": 3, "max_task_attempts": 2, "command_timeout_seconds": 30,
            "expires_at": "2099-01-01T00:00:00Z",
        }
        if self.execution_block is not None:
            self.scope["execution"] = dict(self.execution_block)


class AgentScope13Tests(AgentScope13Fixture):
    def test_scope_13_and_fixture_agent_run_without_codex_on_trusted_host(self):
        compiled = compile_build_plan(requirement()["requirement_ir"], self.plan)
        self.assertEqual(compiled["plan"]["schema_version"], "1.3")
        validate_scope_13(self.plan, self.scope)
        adapter = DeclarativeAdapter(self.profile, executable=self.agent, provider=TrustedHostProvider())
        result = run_agent_workpack(self.plan, self.scope, "IMPLEMENT", adapter=adapter,
                                    provider=TrustedHostProvider(), prompt="hello")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["sandbox_enforcement"], "NONE")
        self.assertEqual(result["assurance"], "CONTRACT_INDEPENDENCE")
        self.assertEqual(result["before_dispatch_calls"], 1)
        self.assertEqual((self.workspace / "src/reader.py").read_text(), "VALUE = 'fixture'\n")
        self.assertFalse(result["workpack_accepted"])
        # The scope validator rejects the old Codex receiver field outright.
        bad = dict(self.scope, codex_executable="/usr/bin/true")
        with self.assertRaises(ValueError):
            validate_scope_13(self.plan, bad)

    def test_agent_and_tool_binaries_are_readable_but_not_task_writable(self):
        self.assertEqual(set(agent_read_roots(self.scope)), {Path(sys.executable), self.agent})
        inside = self.workspace / "fixture-agent"
        shutil.copy2(AGENT, inside)
        inside.chmod(inside.stat().st_mode | stat.S_IXUSR)
        scope = json.loads(json.dumps(self.scope))
        scope["agents"]["fixture"]["executable"] = str(inside)
        with self.assertRaisesRegex(ValueError, "must not be task-writable"):
            validate_scope_13(self.plan, scope)

    def test_verifier_files_bind_every_referenced_checker(self):
        files = verifier_files(self.plan, self.scope)
        self.assertEqual(set(files), {"check.py"})
        self.assertEqual(files["check.py"]["size"], len("print('ok')\n"))
        (self.verifier / "check.py").write_text("print('changed')\n")
        self.assertNotEqual(verifier_files(self.plan, self.scope), files)

    def test_execution_mode_and_provider_must_agree(self):
        seatbelt = json.loads(json.dumps(self.scope))
        seatbelt["sandbox"]["provider"] = "seatbelt"
        with self.assertRaisesRegex(ValueError, "TRUSTED_HOST execution runs unsandboxed"):
            validate_scope_13(self.plan, seatbelt)
        sandboxed = json.loads(json.dumps(self.scope))
        sandboxed["execution"] = {"mode": "SANDBOX"}
        sandboxed["sandbox"]["provider"] = "bwrap"
        validate_scope_13(self.plan, sandboxed)

    def test_none_provider_is_test_only_without_explicit_trusted_host(self):
        scope = json.loads(json.dumps(self.scope))
        del scope["execution"]
        with self.assertRaises(ValueError):
            validate_scope_13(self.plan, scope)
        validate_scope_13(self.plan, scope, test_only=True)

    def test_plan_12_is_not_agent_scope(self):
        plan = dict(self.plan, schema_version="1.2")
        with self.assertRaises(ValueError):
            validate_scope_13(plan, self.scope)


if __name__ == "__main__":
    unittest.main()
