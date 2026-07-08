from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.step_tagger import StepTagger


def test_tag_plan_returns_expected_structure():
    tagger = StepTagger()
    plan = type(
        "Plan",
        (),
        {
            "assumption": "test assumption",
            "confidence": 0.85,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "write_file",
                        "provider_hint": "local_io",
                        "expected_artifact": "output.txt",
                    },
                )(),
                type(
                    "Step",
                    (),
                    {
                        "action": "run_test",
                        "provider_hint": "pytest",
                        "expected_artifact": "test_report.json",
                    },
                ),
            ],
        },
    )()
    result = tagger.tag_plan(plan)
    assert isinstance(result, dict)
    assert "steps" in result
    assert len(result["steps"]) == 2
    tags = [step["tag"] for step in result["steps"]]
    assert len(set(tags)) == 2  # all unique
    first_step = result["steps"][0]
    assert first_step["action"] == plan.steps[0].action
    assert first_step["provider_hint"] == plan.steps[0].provider_hint
    assert first_step["expected_artifact"] == plan.steps[0].expected_artifact


def test_tag_plan_empty_steps():
    tagger = StepTagger()
    empty_plan = type(
        "Plan", (), {"assumption": "no steps plan", "confidence": 1.0, "steps": []}
    )()
    result = tagger.tag_plan(empty_plan)
    assert result == {"steps": []}


def test_reset_resets_counter():
    tagger = StepTagger()
    plan1 = type(
        "Plan",
        (),
        {
            "assumption": "first",
            "confidence": 0.5,
            "steps": [
                type(
                    "Step",
                    (),
                    {"action": "a", "provider_hint": "b", "expected_artifact": "c"},
                )()
            ],
        },
    )()
    plan2 = type(
        "Plan",
        (),
        {
            "assumption": "second",
            "confidence": 0.6,
            "steps": [
                type(
                    "Step",
                    (),
                    {"action": "x", "provider_hint": "y", "expected_artifact": "z"},
                )()
            ],
        },
    )()
    result1 = tagger.tag_plan(plan1)
    assert len(result1["steps"]) == 1
    tag1 = result1["steps"][0]["tag"]
    result2 = tagger.tag_plan(plan2)
    assert len(result2["steps"]) == 1
    tag2 = result2["steps"][0]["tag"]
    assert tag1 != tag2  # different tags due to increment
    tagger.reset()
    result3 = tagger.tag_plan(plan1)
    assert result3["steps"][0]["tag"] == tag1  # cycles back


# RACT 0.1.0 - Initial Public Release
