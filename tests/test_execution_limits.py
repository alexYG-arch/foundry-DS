"""Resource limit helpers; not a security boundary."""

from __future__ import annotations

import resource
import unittest

from harness_foundry_factory.agents.limits import preexec, truncate_output


class LimitTests(unittest.TestCase):
    def test_preexec_sets_supported_limits_without_raising(self):
        # A subprocess avoids fork deadlocks when the full suite is threaded.
        process = __import__("subprocess").run([
            __import__("sys").executable, "-c",
            "import sys; sys.path.insert(0, " + repr(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src")) + "); "
            "from harness_foundry_factory.agents.limits import preexec; "
            "preexec(max_cpu_seconds=5, max_memory_bytes=512*1024*1024, max_fds=64)()"],
            text=True, capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_truncate_output_is_bounded(self):
        self.assertEqual(truncate_output("abc", 10), "abc")
        self.assertTrue(truncate_output("a" * 100, 10).startswith("a" * 10))
        self.assertIn("[TRUNCATED]", truncate_output("a" * 100, 10))


if __name__ == "__main__":
    unittest.main()
