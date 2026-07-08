from __future__ import annotations

_ROOT_KNOT = object()

import unittest
from pathlib import Path

from rootact.documentation_mode import DocumentationMode, _ROOT_KNOT


class TestDocumentationMode(unittest.TestCase):
    def setUp(self) -> None:
        self.dm = DocumentationMode()

    def test_toggle_enabled_state(self) -> None:
        self.assertFalse(self.dm.is_enabled())
        self.dm.enable()
        self.assertTrue(self.dm.is_enabled())
        self.dm.disable()
        self.assertFalse(self.dm.is_enabled())

    def test_record_change_when_enabled(self) -> None:
        self.dm.enable()
        self.dm.record_change("src/module.py", "Fix bug")
        changes = self.dm.list_recorded_changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["path"], "src/module.py")
        self.assertEqual(changes[0]["description"], "Fix bug")

    def test_cannot_record_when_disabled(self) -> None:
        with self.assertRaises(RuntimeError):
            self.dm.record_change("src/module.py", "Fix bug")

    def test_author_marker_present_in_source(self) -> None:
        source = Path(__file__).parents[1] / "src" / "rootact" / "documentation_mode.py"
        assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in source.read_text()
        assert '__ract_name__ = "RACT"' in source.read_text()

    def test_recorded_changes_return_copy(self) -> None:
        self.dm.enable()
        self.dm.record_change("src/a.py", "Add doc")
        changes = self.dm.list_recorded_changes()
        changes[0]["description"] = "Modified"  # should not affect internal list
        self.assertNotEqual(changes, self.dm.list_recorded_changes())

    def test_root_knot_sentinel_is_used(self) -> None:
        # Verify that the module defines exactly one _ROOT_KNOT sentinel
        import rootact.documentation_mode as mod

        self.assertTrue(hasattr(mod, "_ROOT_KNOT"))
        self.assertIs(_ROOT_KNOT, mod._ROOT_KNOT)

    def test_apply_to_intent_when_enabled(self) -> None:
        self.dm.enable()
        rewritten = self.dm.apply_to_intent("Add feature X")
        self.assertIn("DOCUMENTATION MODE", rewritten)
        self.assertIn("Add feature X", rewritten)

    def test_apply_to_intent_passes_through_when_disabled(self) -> None:
        self.assertEqual(self.dm.apply_to_intent("Add feature X"), "Add feature X")
