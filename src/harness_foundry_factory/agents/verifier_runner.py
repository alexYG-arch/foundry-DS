"""Execute an independent verifier contract against CAS and parse its result."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from .base import SANDBOX_NETWORK_UNSUPPORTED
from .verifier import VerifierContract


def run_verifier(contract: VerifierContract, *, verifier_root, cas_root, case_id, provider,
                 model=None):
    verifier_root, cas_root = Path(verifier_root).resolve(), Path(cas_root).resolve()
    code = verifier_root / contract.code_ref
    expected = verifier_root / contract.expected_ref
    identity = contract.verify_files(code, expected)
    argv = list(contract.argv) or [str(__import__("sys").executable), str(code)]
    argv = [item.replace("{code}", str(code)).replace("{expected}", str(expected)) for item in argv]
    command = SimpleNamespace(argv=argv, cwd=cas_root, read_roots=[verifier_root, cas_root],
                              write_roots=[], timeout_seconds=contract.timeout_seconds,
                              environment={"FOUNDRY_EXPECTED": str(expected),
                                           "FOUNDRY_CAS_ROOT": str(cas_root),
                                           "FOUNDRY_CASE_ID": case_id},
                              network=None)
    observed = provider.run(command, before_dispatch=lambda: None)
    if observed.get("status") != "PASS":
        return {"status": "BLOCKED" if observed.get("status") == "VALIDATION_FAILED" else "FAIL",
                "reason_code": observed.get("reason_code"), "identity": identity,
                "stdout": observed.get("stdout"), "stderr": observed.get("stderr"),
                "acceptance": False}
    try:
        result = json.loads(observed.get("stdout") or "{}")
    except json.JSONDecodeError:
        return {"status": "BLOCKED", "reason_code": "VERIFIER_OUTPUT_NOT_JSON",
                "identity": identity, "acceptance": False}
    if not isinstance(result, dict) or result.get("status") not in {"PASS", "FAIL", "BLOCKED"}:
        return {"status": "BLOCKED", "reason_code": "VERIFIER_OUTPUT_SCHEMA",
                "identity": identity, "acceptance": False}
    return {**result, "identity": identity, "acceptance": False,
            "verifier_id": contract.verifier_id, "verifier_owner": contract.owner}
