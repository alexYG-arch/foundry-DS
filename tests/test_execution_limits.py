"""Resource limit helpers; not a security boundary."""

from __future__ import annotations

import resource
import unittest

from harness_foundry_factory.agents.limits import preexec, truncate_output


class LimitTests(unittest.TestCase):
    def test_preexec_sets_supported_limits_without_raising(self):
        # Apply to a child via fork; never lower the test process itself.
        pid = __import__("os").fork()
        if pid == 0:
            try:
                preexec(max_cpu_seconds=5, max_memory_bytes=512 * 1024 * 1024, max_fds=64)()
                __import__("os")._exit(0)
            except Exception:
                __import__("os")._exit(1)
        _, status = __import__("os").waitpid(pid, 0)
        self.assertEqual(__import__("os").waitstatus_to_exitcode(status), 0)

    def test_truncate_output_is_bounded(self):
        self.assertEqual(truncate_output("abc", 10), "abc")
        self.assertTrue(truncate_output("a" * 100, 10).startswith("a" * 10))
        self.assertIn("[TRUNCATED]", truncate_output("a" * 100, 10))


if __name__ == "__main__":
    unittest.main()
