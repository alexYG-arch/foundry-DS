"""M2.0 declarative profile tests; no model or sandbox dispatch."""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from harness_foundry_factory.agents.profile import (
    DeclarativeAdapter,
    DeclarativeProfile,
    ProfileError,
    render_argv,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "tests/fixtures/agents/fixture-profile.json"


class DeclarativeProfileTests(unittest.TestCase):
    def test_loads_profile_and_capabilities(self):
        profile = DeclarativeProfile.load(PROFILE)
        self.assertEqual(profile.adapter_id, "fixture-agent")
        self.assertEqual(profile.capabilities.usage, "UNKNOWN")
        self.assertEqual(profile.capabilities.sandbox, "NONE")
        self.assertEqual(profile.event_map[0]["emit"], "TURN_COMPLETED")
        self.assertEqual(profile.exit_map, {"0": "PASS", "!0": "FAIL"})

    def test_render_replaces_placeholders_without_shell(self):
        adapter = DeclarativeAdapter.load(PROFILE)
        rendered = adapter.render(executable="/bin/echo", workspace="/tmp/work",
                                  prompt="hello world", prompt_file="/tmp/PROMPT.md")
        self.assertEqual(rendered["argv"], ["/bin/echo", "--prompt-file", "/tmp/PROMPT.md"])
        self.assertEqual(rendered["stdin"], "hello world")
        self.assertEqual(rendered["cwd"], "/tmp/work")

    def test_unknown_placeholder_fails(self):
        with self.assertRaises(ProfileError):
            render_argv(["{shell}"], executable="/bin/echo", workspace="/tmp")

    def test_event_and_exit_mapping(self):
        adapter = DeclarativeAdapter.load(PROFILE)
        self.assertEqual(adapter.map_event("result"), "TURN_COMPLETED")
        self.assertEqual(adapter.map_event("other"), "UNKNOWN")
        self.assertEqual(adapter.classify_exit(0), "PASS")
        self.assertEqual(adapter.classify_exit(2), "FAIL")

    def test_probe_checks_regex_and_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "fixture-agent"
            executable.write_text("#!/bin/sh\necho 'fixture-agent 1'\nexit 0\n", encoding="utf-8")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            result = DeclarativeAdapter.load(PROFILE).probe(executable)
            self.assertEqual(result["status"], "PASS", result)
            self.assertTrue(result["regex_matched"])
            self.assertTrue(result["interface_checked"])

    def test_probe_rejects_missing_executable(self):
        result = DeclarativeAdapter.load(PROFILE).probe(Path("/nonexistent/fixture-agent"))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason_code"], "ADAPTER_PROBE_FAILED")

    def test_invalid_capability_and_unknown_event_fail(self):
        value = json.loads(PROFILE.read_text(encoding="utf-8"))
        value["capabilities"]["sandbox"] = "UNKNOWN"
        with self.assertRaises(ProfileError):
            DeclarativeProfile.from_dict(value)
        value = json.loads(PROFILE.read_text(encoding="utf-8"))
        value["unknown_event"] = "DROP"
        with self.assertRaises(ProfileError):
            DeclarativeProfile.from_dict(value)

    def test_unknown_field_fails_closed(self):
        value = json.loads(PROFILE.read_text(encoding="utf-8"))
        value["unexpected"] = True
        with self.assertRaises(ProfileError):
            DeclarativeProfile.from_dict(value)

    def test_dispatch_is_not_enabled_in_m20(self):
        adapter = DeclarativeAdapter.load(PROFILE)
        with self.assertRaises(NotImplementedError):
            adapter.run(object(), before_dispatch=lambda: None)


if __name__ == "__main__":
    unittest.main()
