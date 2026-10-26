#!/usr/bin/env python3
"""Read-only iOS/Android environment probe for the mobile RSI gate.

Prints JSON. It never accepts a license, installs a package, or changes state.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def run(argv, *, env=None, timeout=30):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                env=env, check=False)
        return {"argv": argv, "returncode": result.returncode,
                "stdout": result.stdout[-4000:], "stderr": result.stderr[-2000:]}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"argv": argv, "returncode": None, "error": str(exc)}


def evaluate(checks) -> dict:
    license_blocked = checks["xcode_first_launch"]["returncode"] != 0
    simctl_blocked = checks["simctl_runtimes"]["returncode"] != 0
    blockers = []
    if license_blocked:
        blockers.append("XCODE_LICENSE_NOT_ACCEPTED")
    if simctl_blocked:
        blockers.append("SIMCTL_UNAVAILABLE")
    return {
        "schema_version": "IOS_ENV_CHECK_V1",
        "status": "BLOCKED" if blockers else "PASS",
        "blockers": blockers,
        "checks": checks,
        "writes_performed": False,
        "license_accepted": not license_blocked,
        "simulator_runtime_verified": not simctl_blocked,
    }


def main() -> int:
    clt = {"DEVELOPER_DIR": "/Library/Developer/CommandLineTools", **os.environ}
    checks = {
        "xcode_select": run(["xcode-select", "-p"]),
        "xcode_version": run(["xcodebuild", "-version"]),
        "xcode_first_launch": run(["xcodebuild", "-checkFirstLaunchStatus"]),
        "simctl_runtimes": run(["xcrun", "simctl", "list", "runtimes"]),
        "cocoapods": run(["pod", "--version"], env=clt),
        "flutter": run(["flutter", "--version"], env={**clt, "DEVELOPER_DIR": "/Library/Developer/CommandLineTools"}),
    }
    result = evaluate(checks)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
