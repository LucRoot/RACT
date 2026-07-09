# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for plan_serializers."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from pathlib import Path

from rootact.manager import Plan, Step
from rootact.plan_serializers import (
    load_plan,
    plan_from_dict,
    plan_from_json,
    plan_to_dict,
    plan_to_json,
    save_plan,
    step_from_dict,
    step_to_dict,
)


def _make_step(action: str = "say hello") -> Step:
    return Step(action=action, provider_hint="mock", expected_artifact="greeting.txt")


def _make_plan(steps: list[Step] | None = None) -> Plan:
    return Plan(
        assumption="test assumption",
        confidence=0.9,
        steps=steps or [_make_step()],
    )


def test_step_to_dict_round_trip():
    step = _make_step()
    data = step_to_dict(step)
    restored = step_from_dict(data)
    assert restored == step


def test_plan_to_dict_round_trip():
    plan = _make_plan([_make_step("one"), _make_step("two")])
    data = plan_to_dict(plan)
    restored = plan_from_dict(data)
    assert restored == plan


def test_plan_to_json_is_valid_json():
    plan = _make_plan()
    text = plan_to_json(plan)
    parsed = json.loads(text)
    assert parsed["assumption"] == plan.assumption
    assert parsed["confidence"] == plan.confidence
    assert len(parsed["steps"]) == 1


def test_plan_from_json_round_trip():
    plan = _make_plan([_make_step("a"), _make_step("b")])
    restored = plan_from_json(plan_to_json(plan))
    assert restored == plan


def test_save_and_load_plan(tmp_path: Path):
    plan = _make_plan([_make_step("persist")])
    path = tmp_path / "plan.json"
    save_plan(plan, path)
    loaded = load_plan(path)
    assert loaded == plan


def test_step_with_tool_call_round_trip():
    step = Step(
        action="read config",
        provider_hint="mcp",
        expected_artifact="",
        tool_call={"name": "fs/read", "arguments": {"path": "config.yaml"}},
    )
    data = step_to_dict(step)
    restored = step_from_dict(data)
    assert restored == step


def test_plan_with_tool_call_round_trip():
    plan = _make_plan(
        [
            _make_step("one"),
            Step(
                action="read config",
                provider_hint="mcp",
                expected_artifact="",
                tool_call={"name": "fs/read", "arguments": {"path": "config.yaml"}},
            ),
        ]
    )
    data = plan_to_dict(plan)
    restored = plan_from_dict(data)
    assert restored == plan


# RACT 0.1.1 - Trust and Tooling
