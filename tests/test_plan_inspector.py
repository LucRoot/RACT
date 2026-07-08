__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import unittest

from rootact.plan_inspector import PlanInspector
from rootact.manager import Plan, Step


class TestPlanInspector(unittest.TestCase):
    def setUp(self) -> None:
        self.step1 = Step(
            action="search",
            provider_hint="browser",
            expected_artifact="search_results.json",
        )
        self.step2 = Step(
            action="", provider_hint="browser", expected_artifact="search_results.json"
        )
        self.plan_valid = Plan(
            assumption="The user wants to fetch recent news",
            confidence=0.92,
            steps=[self.step1],
        )
        self.plan_invalid = Plan(
            assumption="", confidence=0.5, steps=[self.step1, self.step2]
        )

    def test_validate_all_good(self) -> None:
        inspector = PlanInspector(self.plan_valid)
        errors = inspector.validate()
        self.assertEqual(errors, [])

    def test_validate_missing_action(self) -> None:
        inspector = PlanInspector(self.plan_invalid)
        errors = inspector.validate()
        self.assertTrue(any("Step with empty action" in e for e in errors))

    def test_validate_missing_provider_hint(self) -> None:
        step_no_hint = Step(
            action="search", provider_hint="", expected_artifact="search_results.json"
        )
        plan = Plan(assumption="test", confidence=0.5, steps=[step_no_hint])
        inspector = PlanInspector(plan)
        errors = inspector.validate()
        self.assertTrue(any("Step with empty provider_hint" in e for e in errors))

    def test_validate_missing_expected_artifact(self) -> None:
        step_no_artifact = Step(
            action="search", provider_hint="browser", expected_artifact=""
        )
        plan = Plan(assumption="test", confidence=0.5, steps=[step_no_artifact])
        inspector = PlanInspector(plan)
        errors = inspector.validate()
        self.assertTrue(any("Step with empty expected_artifact" in e for e in errors))

    def test_summarize_output(self) -> None:
        inspector = PlanInspector(self.plan_valid)
        summary = inspector.summarize()
        self.assertIn("Assumption: The user wants to fetch recent news", summary)
        self.assertIn("Confidence: 0.92", summary)
        self.assertIn("action=search", summary)
        self.assertIn("provider_hint=browser", summary)
        self.assertIn("expected_artifact=search_results.json", summary)


# RACT 0.1.0 - Initial Public Release
