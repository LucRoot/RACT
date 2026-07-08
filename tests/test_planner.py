# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the Planner module."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.manager import Plan, Step
from rootact.planner import Planner
from rootact.rooted import Rooted


class FakeManager:
    """A minimal fake Manager for Planner unit tests."""

    def __init__(self, plan_rooted: Rooted[Plan]) -> None:
        self._plan = plan_rooted

    def plan(self, intent: str) -> Rooted[Plan]:
        return self._plan


def _make_step(action: str = "write hello") -> Step:
    return Step(action=action, provider_hint="mock", expected_artifact="hello.txt")


def _make_plan(
    steps: list[Step], assumption: str = "test assumption", confidence: float = 0.9
) -> Plan:
    return Plan(assumption=assumption, confidence=confidence, steps=steps)


def test_planner_returns_plan_when_manager_produces_valid_plan():
    plan = _make_plan([_make_step()])
    manager = FakeManager(
        Rooted(value=plan, assumption="ok", confidence=0.9, provenance=["fake"])
    )
    planner = Planner(manager)

    result = planner.plan("test intent")

    assert result.is_ok()
    assert result.unwrap() is plan
    assert result.confidence == 0.9


def test_planner_returns_error_when_plan_has_no_steps():
    empty_plan = _make_plan(steps=[])
    manager = FakeManager(
        Rooted(
            value=empty_plan, assumption="empty", confidence=0.9, provenance=["fake"]
        )
    )
    planner = Planner(manager)

    result = planner.plan("test intent")

    assert not result.is_ok()
    assert result.error is not None
    assert "no steps" in str(result.error).lower()


def test_planner_propagates_manager_failure():
    manager = FakeManager(
        Rooted(
            value=None,
            assumption="manager failed",
            confidence=0.0,
            provenance=["fake"],
            error="provider unreachable",
        )
    )
    planner = Planner(manager)

    result = planner.plan("test intent")

    assert not result.is_ok()
    assert result.error == "provider unreachable"
