# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass
from typing import List

from rootact.manager import Plan


@dataclass(frozen=True)
class AnalysisResult:
    """Result of analyzing a Plan for potential failure points."""

    risk_score: float
    high_risk_steps: List[int]
    suggestions: List[str]


def analyze_plan(plan: Plan) -> AnalysisResult:
    """Analyze a plan and return risk assessment.

    This helper evaluates the plan's steps for high-risk actions
    based on provider hints and expected artifacts, providing a
    simple risk score and actionable suggestions.

    Args:
        plan: The plan to analyze.

    Returns:
        AnalysisResult: Risk assessment details.
    """
    high_risk_steps = []
    for idx, step in enumerate(plan.steps):
        hint = step.provider_hint.lower()
        if "unsafe" in hint or "delete" in hint or "overwrite" in hint:
            high_risk_steps.append(idx)
    risk_score = len(high_risk_steps) / len(plan.steps) if plan.steps else 0.0
    suggestions = [
        f"Consider reviewing step {idx} for safety" for idx in high_risk_steps
    ]
    return AnalysisResult(
        risk_score=risk_score,
        high_risk_steps=high_risk_steps,
        suggestions=suggestions,
    )
