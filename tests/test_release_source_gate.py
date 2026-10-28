"""Required release-source checks cannot go green through skipped tests."""

import importlib.util
import io
import json
from pathlib import Path
import tomllib
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_source_check", ROOT / "tools/check_release_source.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ReleaseSourceGateTests(unittest.TestCase):
    def run_case(self, body):
        class Example(unittest.TestCase):
            def test_required(self):
                body(self)
        return gate.check_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Example), stream=io.StringIO())

    def test_real_pass_and_zero_discovery(self):
        self.assertEqual(self.run_case(lambda test: test.assertEqual(2 + 2, 4))["status"], "PASS")
        self.assertEqual(gate.check_suite(unittest.TestSuite(), stream=io.StringIO())["status"], "FAIL")

    def test_required_skip_is_failure_even_when_unittest_reports_ok(self):
        result = self.run_case(lambda test: test.skipTest("not configured"))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["skipped"][0]["reason"], "not configured")
        self.assertEqual(result["passed"], 0)

    def test_assertion_crash_and_failed_subtest_are_not_passes(self):
        def crash(test):
            raise RuntimeError("broken infrastructure")
        def subtest(test):
            with test.subTest("nested"):
                test.fail("wrong output")
        for body in (lambda test: test.fail("wrong output"), crash, subtest):
            self.assertEqual(self.run_case(body)["status"], "FAIL")

    def test_expected_failure_is_not_release_acceptance(self):
        class Example(unittest.TestCase):
            @unittest.expectedFailure
            def test_required(self):
                self.fail("known defect")
        result = gate.check_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Example), stream=io.StringIO())
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(len(result["expected_failures"]), 1)

    def test_missing_or_empty_required_module_fails_aggregate(self):
        # No recursive real suite run. Simulate ordinary runner success while
        # independently testing discovery failure and explicit acceptance flags.
        fake_tests = {"status": "PASS"}
        from subprocess import CompletedProcess
        fake_skill = CompletedProcess([], 0, '{"status":"PASS"}', "")
        for name in ("does_not_exist", "test_release_source_gate"):
            with patch.object(gate, "REQUIRED_MODULES", (name,)), \
                 patch.object(gate, "check_suite", return_value=fake_tests), \
                 patch.object(gate.unittest.TestLoader, "loadTestsFromName", return_value=unittest.TestSuite()), \
                 patch.object(gate.subprocess, "run", return_value=fake_skill):
                result = gate.source_checks()
            self.assertEqual(result["status"], "SOURCE_CHECKS_FAIL")
            self.assertTrue(result["missing_modules"] or result["empty_modules"])
            self.assertFalse(result["release_accepted"])
            self.assertFalse(result["harness_e2e_verified"])

    def test_platform_sets_only_add_real_sandbox_modules_where_they_exist(self):
        common = set(gate.REQUIRED_MODULES)
        darwin, linux = set(gate.required_modules("darwin")), set(gate.required_modules("linux"))
        self.assertTrue(common <= darwin and common <= linux)
        self.assertEqual(darwin - common, {"test_sandbox_seatbelt", "test_agent_scope13_seatbelt"})
        self.assertFalse(linux & {"test_sandbox_seatbelt", "test_agent_scope13_seatbelt"})
        self.assertNotIn("test_sandbox_seatbelt", common)
        for module in gate.required_modules("darwin") + gate.required_modules("linux"):
            self.assertTrue((ROOT / "tests" / f"{module}.py").is_file(), module)
        # Everything the generic release ships from the A3/A4 work is gated.
        self.assertTrue({"test_revision_store_dedup", "test_control_view", "test_a3a4_helpers"} <= common)

    def test_license_and_canonical_repository_are_shipped_metadata(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["license-files"], ["LICENSE"])
        self.assertEqual(project["urls"]["Repository"], "https://github.com/alexYG-arch/Harness_Foundry")
        license_text = (ROOT / "LICENSE").read_text()
        self.assertIn("Permission is hereby granted, free of charge", license_text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', license_text)
        manifest = json.loads((ROOT / "FACTORY_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], project["version"])


if __name__ == "__main__":
    unittest.main()
