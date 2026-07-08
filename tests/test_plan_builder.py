__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import unittest

from rootact.plan_builder import PlanBuilder


class TestPlanBuilder(unittest.TestCase):
    def test_build_creates_plan_with_steps(self):
        description = "list files;fs;file_list.csv, download model;hf;model.pt"
        builder = PlanBuilder(description)
        plan = builder.build()
        self.assertEqual(plan.assumption, "Extracted from description")
        self.assertAlmostEqual(plan.confidence, 0.9)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].action, "list files")
        self.assertEqual(plan.steps[0].provider_hint, "fs")
        self.assertEqual(plan.steps[0].expected_artifact, "file_list.csv")
        self.assertEqual(plan.steps[1].action, "download model")
        self.assertEqual(plan.steps[1].provider_hint, "hf")
        self.assertEqual(plan.steps[1].expected_artifact, "model.pt")

    def test_invalid_step_format_raises(self):
        description = "invalid step without enough parts"
        builder = PlanBuilder(description)
        with self.assertRaises(ValueError) as ctx:
            builder.build()
        self.assertIn("Invalid step format", str(ctx.exception))

    def test_empty_description_returns_empty_plan(self):
        builder = PlanBuilder("")
        plan = builder.build()
        self.assertEqual(len(plan.steps), 0)
        self.assertEqual(plan.assumption, "Extracted from description")
        self.assertAlmostEqual(plan.confidence, 0.9)


# RACT 0.1.0 - Initial Public Release
