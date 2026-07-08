__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import unittest
from rootact.intent_parser import IntentParser


class TestIntentParser(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IntentParser()

    def test_parse_list_action(self) -> None:
        intent = self.parser.parse("List recent blog posts")
        self.assertEqual(intent.description, "list recent blog posts")
        self.assertEqual(intent.confidence, 0.9)
        self.assertEqual(len(intent.plan.steps), 1)
        step = intent.plan.steps[0]
        self.assertEqual(step.action, "list")
        self.assertEqual(step.provider_hint, "default")
        self.assertEqual(step.expected_artifact, "output")

    def test_parse_create_action(self) -> None:
        intent = self.parser.parse("Create a new user")
        self.assertEqual(intent.description, "create a new user")
        self.assertEqual(intent.confidence, 0.9)
        self.assertEqual(len(intent.plan.steps), 1)
        step = intent.plan.steps[0]
        self.assertEqual(step.action, "create")
        self.assertEqual(step.provider_hint, "default")
        self.assertEqual(step.expected_artifact, "output")

    def test_parse_delete_action(self) -> None:
        intent = self.parser.parse("Delete old logs")
        self.assertEqual(intent.description, "delete old logs")
        self.assertEqual(intent.confidence, 0.9)
        self.assertEqual(len(intent.plan.steps), 1)
        step = intent.plan.steps[0]
        self.assertEqual(step.action, "delete")
        self.assertEqual(step.provider_hint, "default")
        self.assertEqual(step.expected_artifact, "output")

    def test_parse_unknown_action(self) -> None:
        intent = self.parser.parse("Random text without keywords")
        self.assertEqual(intent.description, "random text without keywords")
        self.assertEqual(intent.confidence, 0.9)
        self.assertEqual(len(intent.plan.steps), 1)
        step = intent.plan.steps[0]
        self.assertEqual(step.action, "noop")
        self.assertEqual(step.provider_hint, "default")
        self.assertEqual(step.expected_artifact, "output")


if __name__ == "__main__":
    unittest.main()
# RACT 0.1.0 - Initial Public Release
