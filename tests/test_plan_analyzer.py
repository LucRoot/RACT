from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.manager import Plan, Step
from rootact.plan_analyzer import analyze_plan, AnalysisResult


def test_analyze_plan_basic():
    plan = Plan(
        assumption="Test assumption",
        confidence=0.9,
        steps=[
            Step(action="read", provider_hint="safe", expected_artifact="data"),
            Step(action="delete", provider_hint="unsafe", expected_artifact="temp"),
        ],
    )
    result: AnalysisResult = analyze_plan(plan)
    assert result.risk_score == 0.5
    assert result.high_risk_steps == [1]
    assert len(result.suggestions) == 1
    assert "step 1" in result.suggestions[0]


def test_analyze_plan_no_steps():
    plan = Plan(assumption="Empty", confidence=1.0, steps=[])
    result = analyze_plan(plan)
    assert result.risk_score == 0.0
    assert result.high_risk_steps == []
    assert result.suggestions == []


def test_analyze_plan_all_safe():
    plan = Plan(
        assumption="Safe workflow",
        confidence=0.8,
        steps=[
            Step(action="list", provider_hint="read", expected_artifact="files"),
            Step(action="copy", provider_hint="safe", expected_artifact="backup"),
        ],
    )
    result = analyze_plan(plan)
    assert result.risk_score == 0.0
    assert result.high_risk_steps == []
    assert result.suggestions == []


# RACT 0.1.0 - Initial Public Release
