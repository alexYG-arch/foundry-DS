"""Carrier-neutral instruction discovery: Codex/DSH AGENTS, Claude CLAUDE.md."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from harness_foundry_factory.coding_process import instruction_read_preflight
from harness_foundry_factory.local_process import LocalProcessError


class CarrierInstructionTests(unittest.TestCase):
    def root(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        (root / ".git").mkdir()
        return root

    def test_codex_and_dsh_use_agents(self):
        for carrier in ("codex", "dsh"):
            with self.subTest(carrier=carrier):
                root = self.root()
                (root / "AGENTS.md").write_text("rules\n")
                with patch("harness_foundry_factory.coding_process.client_state_root", return_value=root):
                    result = instruction_read_preflight(root, [root], carrier=carrier)
                self.assertEqual(result["status"], "READ_SCOPE_COVERED")
                self.assertTrue(result["instruction_files"][-1].endswith("AGENTS.md"))

    def test_claude_uses_claude_md(self):
        root = self.root()
        (root / "CLAUDE.md").write_text("rules\n")
        with patch("harness_foundry_factory.coding_process.client_state_root", return_value=root):
            result = instruction_read_preflight(root, [root], carrier="claude")
        self.assertEqual(result["status"], "READ_SCOPE_COVERED")
        self.assertTrue(result["instruction_files"][-1].endswith("CLAUDE.md"))

    def test_unknown_carrier_fails_closed(self):
        with self.assertRaises(LocalProcessError):
            instruction_read_preflight(self.root(), [], carrier="unknown")


if __name__ == "__main__":
    unittest.main()
