"""Trusted-host provider: explicit no-sandbox baseline, not a sandbox PASS."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness_foundry_factory.agents.sandbox_trusted import TrustedHostProvider


class TrustedHostTests(unittest.TestCase):
    def test_runs_without_claiming_sandbox(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = Path(d).resolve()
            command = SimpleNamespace(argv=["/bin/echo", "TRUSTED_OK"], cwd=cwd, timeout_seconds=10,
                                      environment={}, network=None)
            result = TrustedHostProvider().run(command, before_dispatch=lambda: None)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["stdout"].strip(), "TRUSTED_OK")
            self.assertEqual(result["sandbox_enforcement"], "NONE")
            self.assertEqual(result["assurance"], "CONTRACT_INDEPENDENCE")

    def test_network_is_still_explicitly_rejected(self):
        command = SimpleNamespace(argv=["/bin/true"], cwd=Path("/tmp"), timeout_seconds=5,
                                  environment={}, network={"mode": "REMOTE_SERVICE"})
        result = TrustedHostProvider().run(command, before_dispatch=lambda: None)
        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertFalse(result["workload_started"])


if __name__ == "__main__":
    unittest.main()
