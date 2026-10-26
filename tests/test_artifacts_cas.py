"""Staging -> CAS: hash identity, immutability, path checks."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from harness_foundry_factory.agents.artifacts import ArtifactStoreError, ingest, write_manifest


class CasTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.staging = self.root / "staging"; self.staging.mkdir()
        self.cas = self.root / "cas"; self.cas.mkdir()

    def test_ingest_hashes_and_freezes_artifact(self):
        (self.staging / "proof.txt").write_text("CAS_OK")
        result = ingest(self.staging, self.cas, [{"artifact_id": "PROOF", "path": "proof.txt"}], attempt_id="A1")
        self.assertEqual(result["status"], "PASS")
        entry = result["manifest"]["entries"][0]
        expected = hashlib.sha256(b"CAS_OK").hexdigest()
        self.assertEqual(entry["sha256"], expected)
        target = self.cas / expected[:2] / expected
        self.assertTrue(target.is_file())
        self.assertEqual(target.stat().st_mode & 0o777, 0o444)
        self.assertEqual(target.read_text(), "CAS_OK")

    def test_cas_object_is_not_overwritten_and_manifest_is_new(self):
        (self.staging / "proof.txt").write_text("CAS_OK")
        result = ingest(self.staging, self.cas, [{"artifact_id": "PROOF", "path": "proof.txt"}], attempt_id="A1")
        ingest(self.staging, self.cas, [{"artifact_id": "PROOF", "path": "proof.txt"}], attempt_id="A2")
        write_manifest(result["manifest"], self.cas)
        with self.assertRaises(ArtifactStoreError):
            write_manifest(result["manifest"], self.cas)
        count = sum(1 for p in self.cas.rglob("*") if p.is_file() and p.name != "A1.json")
        self.assertEqual(count, 1)

    def test_missing_and_traversal_are_rejected(self):
        with self.assertRaises(ArtifactStoreError):
            ingest(self.staging, self.cas, [{"artifact_id": "X", "path": "missing"}], attempt_id="A1")
        with self.assertRaises(ArtifactStoreError):
            ingest(self.staging, self.cas, [{"artifact_id": "X", "path": "../outside"}], attempt_id="A1")


if __name__ == "__main__":
    unittest.main()
