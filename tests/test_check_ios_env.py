"""Read-only iOS environment evaluator tests; no license or install action."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ios_env_check", ROOT / "tools/check_ios_env.py")
ios = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ios)


def checks(license_rc, simctl_rc):
    return {
        "xcode_select": {"returncode": 0},
        "xcode_version": {"returncode": 0},
        "xcode_first_launch": {"returncode": license_rc},
        "simctl_runtimes": {"returncode": simctl_rc},
        "cocoapods": {"returncode": 0},
        "flutter": {"returncode": 0},
    }


class IosEnvCheckTests(unittest.TestCase):
    def test_pass_requires_license_and_simctl(self):
        result = ios.evaluate(checks(0, 0))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["license_accepted"])
        self.assertTrue(result["simulator_runtime_verified"])
        self.assertFalse(result["writes_performed"])

    def test_license_blocker_is_explicit(self):
        result = ios.evaluate(checks(69, 0))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blockers"], ["XCODE_LICENSE_NOT_ACCEPTED"])
        self.assertFalse(result["license_accepted"])

    def test_simctl_blocker_is_explicit(self):
        result = ios.evaluate(checks(0, 1))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blockers"], ["SIMCTL_UNAVAILABLE"])

    def test_both_blockers_are_reported(self):
        result = ios.evaluate(checks(69, 1))
        self.assertEqual(result["blockers"], ["XCODE_LICENSE_NOT_ACCEPTED", "SIMCTL_UNAVAILABLE"])


if __name__ == "__main__":
    unittest.main()
