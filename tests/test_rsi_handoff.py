"""A4 handoff: baseline + delta + evidence, history by reference only."""

import hashlib
import unittest

from harness_foundry_factory.rsi_handoff import HandoffError, build_current_view, diff_views, render_markdown

SHA = hashlib.sha256(b"baseline").hexdigest()


class HandoffTests(unittest.TestCase):
    def view(self):
        return build_current_view(baseline={"id": "B", "sha256": SHA}, changes=[{"id": "C1"}],
            affected_assertions=[{"id": "A1", "change_ids": ["C1"]}], evidence=[],
            history_refs=[{"id": "H", "sha256": SHA}], pending=[])

    def test_history_is_reference_not_embedded_text(self):
        view = build_current_view(
            baseline={"id": "B1", "sha256": SHA},
            changes=[{"id": "C1", "kind": "FILE"}],
            affected_assertions=[{"id": "A1", "status": "PENDING"}],
            evidence=[{"id": "E1", "sha256": SHA}],
            history_refs=[{"id": "H1", "sha256": SHA}],
            pending=["A1"],
        )
        self.assertEqual(view["schema_version"], "RSI_CURRENT_VIEW_V1")
        self.assertFalse(view["history_content_embedded"])
        self.assertIn("## History references", render_markdown(view))
        with self.assertRaises(HandoffError):
            build_current_view(baseline={"id": "B1", "sha256": SHA}, changes=[], affected_assertions=[],
                               evidence=[], history_refs=[{"id": "H1", "sha256": SHA, "text": "old report"}])

    def test_diff_views_reports_identity_changes(self):
        first = self.view()
        second = self.view()
        second["affected_assertions"] = [{"id": "A2", "change_ids": ["C1"], "status": "PENDING"}]
        diff = diff_views(first, second)
        self.assertEqual(diff["sections"]["affected_assertions"]["added"], ["A2"])
        self.assertEqual(diff["sections"]["affected_assertions"]["removed"], ["A1"])

    def test_baseline_requires_hash(self):
        with self.assertRaises(HandoffError):
            build_current_view(baseline={"id": "B1"}, changes=[], affected_assertions=[], evidence=[])


if __name__ == "__main__":
    unittest.main()
