"""M0 golden fixture: lock one Codex JSONL stream and its parser result."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from harness_foundry_factory.coding_events import observe_coding_process

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/agent_events/codex/basic.jsonl"
FIXTURE_SHA256 = "5a73b7bcdd3ac72a2ea9e6105c8ac3fa971c1686e56458758f5902cb1e3c1255"


class CodexGoldenFixtureTests(unittest.TestCase):
    def test_fixture_bytes_are_locked(self):
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), FIXTURE_SHA256)

    def test_observer_result_is_stable(self):
        result = observe_coding_process(FIXTURE.read_bytes(), exit_code=0)
        self.assertEqual(result["status"], "MODEL_TURN_COMPLETED")
        self.assertEqual(result["reason_code"], "CODEX_TURN_COMPLETED_NOT_WORKPACK_ACCEPTANCE")
        self.assertEqual(result["thread_id"], "thread-golden-1")
        self.assertEqual(result["final_message"], "golden")
        self.assertEqual(result["event_count"], 4)
        self.assertEqual(result["usage"], {"input_tokens": 10, "output_tokens": 5})
        self.assertFalse(result["workpack_accepted"])

    def test_protocol_error_is_not_a_pass(self):
        result = observe_coding_process(b'{"type":"thread.started"}\n', exit_code=0)
        self.assertEqual(result["status"], "UNKNOWN_SIDE_EFFECT")
        self.assertEqual(result["reason_code"], "CODEX_EVENT_PROTOCOL_INVALID")


if __name__ == "__main__":
    unittest.main()
