"""Independent verifier identity: code/expected hashes, CAS-only policy."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from harness_foundry_factory.agents.verifier import VerifierContract, VerifierContractError


class VerifierContractTests(unittest.TestCase):
    def test_hashes_must_match_both_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); code = root/"check.py"; expected = root/"expected.json"
            code.write_text("print('ok')\n"); expected.write_text('{"ok": true}\n')
            contract = VerifierContract.from_dict({
                "verifier_id": "V1", "owner": "verifier-owner",
                "code_ref": "check.py", "code_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
                "expected_ref": "expected.json", "expected_sha256": hashlib.sha256(expected.read_bytes()).hexdigest(),
                "input_policy": "CAS_ONLY"})
            result = contract.verify_files(code, expected)
            self.assertEqual(result["status"], "PASS"); self.assertTrue(result["independent"])
            self.assertFalse(result["acceptance"])
            expected.write_text("changed")
            with self.assertRaises(VerifierContractError):
                contract.verify_files(code, expected)

    def test_policy_and_hashes_are_strict(self):
        with self.assertRaises(VerifierContractError):
            VerifierContract.from_dict({"verifier_id": "V1", "owner": "o", "code_ref": "c",
                "code_sha256": "x", "expected_ref": "e", "expected_sha256": "y"})
        with self.assertRaises(VerifierContractError):
            VerifierContract.from_dict({"verifier_id": "V1", "owner": "o", "code_ref": "c",
                "code_sha256": "0"*64, "expected_ref": "e", "expected_sha256": "0"*64,
                "input_policy": "WORKSPACE"})


if __name__ == "__main__":
    unittest.main()
