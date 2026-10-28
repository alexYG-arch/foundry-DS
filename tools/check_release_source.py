#!/usr/bin/env python3
"""Run required public source checks; never grant whole-release acceptance.

No model, target build, private Case, normative sibling or release upload is
needed. Native opt-in and full compatibility tests remain separate obligations.

The required set is platform-aware: ``REQUIRED_MODULES`` must pass everywhere,
``PLATFORM_MODULES`` adds the modules that exercise a platform's real sandbox.
Modules outside the current platform's set are not loaded at all, so the gate
keeps its "zero skips, zero failures" meaning instead of failing on every
Linux runner because macOS seatbelt is absent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = (
    "test_product_identity",
    "test_build_review",
    "test_build_plan",
    "test_build_authoring",
    "test_source_intake",
    "test_rsi_adoption",
    "test_rsi_cases",
    "test_rsi_review",
    "test_rsi_tdd",
    "test_rsi_wiki",
    "test_rsi_delivery",
    "test_revision_control_store",
    "test_acceptance_contract",
    "test_build_entrypoint",
    "test_build_runtime",
    "test_build_runtime_context",
    "test_build_reconciliation",
    "test_build_reassessment",
    "test_build_correction",
    "test_build_correction_budget",
    "test_build_correction_runtime",
    "test_build_preview",
    "test_coding_reconnect",
    "test_build_observation_race",
    "test_build_model_defaults",
    "test_build_daily_model_defaults",
    "test_coding_defaults",
    "test_model_service_configuration",
    "test_model_configuration_observation",
    "test_build_model_service",
    "test_python_startup",
    "test_build_rebind",
    "test_build_check_protocol",
    "test_portable_local_cli",
    "test_skill_contract",
    "test_release_source_gate",
    "test_generic_distribution",
    "test_r3_distribution",
    "test_capability_distribution",
    "test_r3_behavior_baseline",
    "test_build_resource_lifecycle",
    "test_build_replan",
    "test_verification_resources",
    "test_build_resources",
    "test_resource_network",
    "test_resource_credentials",
    "test_resource_credential_observation",
    "test_process_cancellation",
    "test_process_observation",
    "test_committed_distribution",
    "test_route_retirement",
    "test_test_execution",
    "test_release_acceptance_adapters",
    "test_agent_contract",
    "test_agent_contract_golden",
    "test_agents_package",
    "test_declarative_profile",
    "test_declarative_dispatch",
    "test_check_ios_env",
    "test_sandbox_trusted",
    "test_agent_scope13",
    "test_dsh_adapter",
    "test_api_adapter",
    "test_agent_controller",
    "test_agent_controller_e2e",
    "test_carrier_instructions",
    "test_import_design_case",
    "test_egress_proxy",
    "test_host_gateway",
    "test_artifacts_cas",
    "test_verifier_contract",
    "test_execution_limits",
    "test_verifier_runner",
    "test_check_design_record",
    "test_revision_store_dedup",
    "test_control_view",
    "test_a3a4_helpers",
)
# Real-sandbox modules: loaded only where that sandbox exists. The gate still
# forbids skips inside whatever set it loads.
PLATFORM_MODULES = {
    "darwin": ("test_sandbox_seatbelt", "test_agent_scope13_seatbelt"),
    "linux": (),
}


def platform_key(platform: str | None = None) -> str:
    value = platform or sys.platform
    return "darwin" if value == "darwin" else "linux" if value.startswith("linux") else value


def required_modules(platform: str | None = None) -> tuple[str, ...]:
    return tuple(REQUIRED_MODULES) + tuple(PLATFORM_MODULES.get(platform_key(platform), ()))


class RequiredResult(unittest.TextTestResult):
    """unittest's ordinary success permits skips/xfail; this gate must not."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed += 1


def check_suite(suite: unittest.TestSuite, *, stream=None) -> dict:
    discovered = suite.countTestCases()
    result = unittest.TextTestRunner(
        stream=stream or sys.stderr, verbosity=2, resultclass=RequiredResult,
    ).run(suite)
    passed = (
        discovered > 0 and result.testsRun == discovered
        and result.passed == discovered and result.wasSuccessful()
        and not result.skipped and not result.expectedFailures
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "discovered": discovered,
        "executed": result.testsRun,
        "passed": result.passed,
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "expected_failures": [test.id() for test, _ in result.expectedFailures],
        "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
    }


def _release_receipt(path):
    import hashlib
    import subprocess
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip()
    valid = (value.get("schema_version") == "RELEASE_RECEIPT_V1"
             and value.get("release_accepted") is True
             and value.get("commit") == head
             and not value.get("findings"))
    return value, digest, head, valid


def source_checks(receipt=None) -> dict:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT / "src"))
    loader = unittest.TestLoader()
    suites = []
    missing = []
    empty = []
    modules = required_modules()
    for module in modules:
        if not (ROOT / "tests" / f"{module}.py").is_file():
            missing.append(module)
            continue
        loaded = loader.loadTestsFromName(module)
        if not loaded.countTestCases():
            empty.append(module)
        suites.append(loaded)
    tests = check_suite(unittest.TestSuite(suites))
    skill = subprocess.run(
        [sys.executable, "-B", str(ROOT / "tools/validate_skill.py")],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=60,
    )
    try:
        skill_result = json.loads(skill.stdout)
    except ValueError:
        skill_result = {"status": "FAIL", "error": "Skill checker did not emit JSON"}
    skill_ok = isinstance(skill_result, dict) and skill_result.get("status") == "PASS" and skill.returncode == 0
    passed = tests["status"] == "PASS" and not missing and not empty and not loader.errors and skill_ok
    receipt_value = None
    if receipt is not None:
        try:
            receipt_value, receipt_digest, head, receipt_valid = _release_receipt(receipt)
        except (OSError, ValueError) as exc:
            receipt_value, receipt_digest, head, receipt_valid = {"error": str(exc)}, None, None, False
        if not receipt_valid:
            passed = False
    return {
        "schema_version": "1.0",
        "status": "SOURCE_CHECKS_PASS" if passed else "SOURCE_CHECKS_FAIL",
        "scope": "PUBLIC_GENERIC_SOURCE_WITH_HISTORICAL_REGRESSION_AND_PORTABLE_SMOKE",
        "historical_regression_is_current_product_acceptance": False,
        "platform": sys.platform,
        "platform_set": platform_key(),
        "platform_modules": list(PLATFORM_MODULES.get(platform_key(), ())),
        "required_modules": list(modules),
        "missing_modules": missing,
        "empty_modules": empty,
        "load_errors": loader.errors,
        "tests": tests,
        "skill": skill_result,
        "release_accepted": bool(receipt_value and receipt_valid) if receipt is not None else False,
        "harness_e2e_verified": bool(receipt_value and receipt_valid) if receipt is not None else False,
        "release_receipt": ({"path": str(receipt), "sha256": receipt_digest,
                             "commit": head, "valid": receipt_valid} if receipt is not None else None),
        "not_run": [] if receipt_value and receipt_valid else [
            "FULL_COMPATIBILITY_REGRESSION", "PHYSICAL_SIBLING_SPEC_CHECK",
            "NATIVE_CODEX_ACCEPTANCE", "SAME_PACKAGE_TWO_CASES",
            "CLEAN_COMMITTED_RELEASE_BUILD", "PUBLICATION",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write JSON to a new diagnostic file; never overwrite.")
    parser.add_argument("--receipt", type=Path, help="Validate a RELEASE_RECEIPT_V1 and bind release status to it")
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("--report must name a new file")
    try:
        report = source_checks(receipt=args.receipt)
    except Exception as exc:
        report = {"status": "SOURCE_CHECKS_FAIL", "error": f"{type(exc).__name__}: {exc}",
                  "release_accepted": False, "harness_e2e_verified": False}
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as output:
            output.write(serialized + "\n")
    print(serialized)
    return 0 if report["status"] == "SOURCE_CHECKS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
