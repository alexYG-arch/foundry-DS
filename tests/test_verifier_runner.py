"""Run an independent verifier contract against CAS via TrustedHostProvider."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from harness_foundry_factory.agents.sandbox_trusted import TrustedHostProvider
from harness_foundry_factory.agents.verifier import VerifierContract
from harness_foundry_factory.agents.verifier_runner import run_verifier


class VerifierRunnerTests(unittest.TestCase):
    def test_verifier_reads_cas_and_returns_structured_result(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve(); verifier = root/"verifier"; verifier.mkdir()
            cas = root/"cas"; cas.mkdir()
            code = verifier/"check.py"; expected = verifier/"expected.json"
            code.write_text("import os,json;print(json.dumps({'status':'PASS','case_id':os.environ['FOUNDRY_CASE_ID']}))\n")
            expected.write_text('{"ok": true}\n')
            contract = VerifierContract.from_dict({
                "verifier_id": "V1", "owner": "verifier-owner",
                "code_ref": "check.py", "code_sha256": hashlib.sha256(code.read_bytes()).hexdigest(),
                "expected_ref": "expected.json", "expected_sha256": hashlib.sha256(expected.read_bytes()).hexdigest(),
                "argv": [sys.executable, "{code}"]})
            result = run_verifier(contract, verifier_root=verifier, cas_root=cas,
                                  case_id="C1", provider=TrustedHostProvider())
            self.assertEqual(result["status"], "PASS", result)
            self.assertEqual(result["case_id"], "C1")
            self.assertFalse(result["acceptance"])
            self.assertTrue(result["identity"]["independent"])

    def test_verifier_identity_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve(); verifier = root/"verifier"; verifier.mkdir(); cas = root/"cas"; cas.mkdir()
            code = verifier/"check.py"; expected = verifier/"expected.json"
            code.write_text("print('{}')\n"); expected.write_text("x")
            contract = VerifierContract.from_dict({
                "verifier_id": "V1", "owner": "o", "code_ref": "check.py",
                "code_sha256": "0"*64, "expected_ref": "expected.json", "expected_sha256": "0"*64})
            with self.assertRaises(Exception):
                run_verifier(contract, verifier_root=verifier, cas_root=cas,
                             case_id="C1", provider=TrustedHostProvider())


if __name__ == "__main__":
    unittest.main()
