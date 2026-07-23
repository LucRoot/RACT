# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Serialize and deserialize RACT plans and steps.

A small utility module so plans can be saved to disk, sent over the wire, or
stored in a database without coupling the rest of the system to JSON details.
"""

import json
from pathlib import Path
from typing import Any

from ract.manager import Plan, Step


def step_to_dict(step: Step) -> dict[str, Any]:
    """Convert a Step to a plain dictionary."""
    result: dict[str, Any] = {
        "action": step.action,
        "provider_hint": step.provider_hint,
        "expected_artifact": step.expected_artifact,
    }
    if step.tool_call is not None:
        result["tool_call"] = step.tool_call
    return result


def step_from_dict(data: dict[str, Any]) -> Step:
    """Reconstruct a Step from a dictionary."""
    return Step(
        action=data["action"],
        provider_hint=data["provider_hint"],
        expected_artifact=data["expected_artifact"],
        tool_call=data.get("tool_call"),
    )


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    """Convert a Plan to a plain dictionary."""
    return {
        "assumption": plan.assumption,
        "confidence": plan.confidence,
        "steps": [step_to_dict(step) for step in plan.steps],
    }


def plan_from_dict(data: dict[str, Any]) -> Plan:
    """Reconstruct a Plan from a dictionary."""
    return Plan(
        assumption=data["assumption"],
        confidence=data["confidence"],
        steps=[step_from_dict(step) for step in data["steps"]],
    )


def plan_to_json(plan: Plan) -> str:
    """Serialize a Plan to a JSON string."""
    return json.dumps(plan_to_dict(plan), indent=2)


def plan_from_json(text: str) -> Plan:
    """Deserialize a Plan from a JSON string."""
    return plan_from_dict(json.loads(text))


def save_plan(plan: Plan, path: str | Path) -> None:
    """Save a Plan to *path* as JSON."""
    Path(path).write_text(plan_to_json(plan), encoding="utf-8")


def load_plan(path: str | Path) -> Plan:
    """Load a Plan from a JSON file at *path*."""
    return plan_from_json(Path(path).read_text(encoding="utf-8"))


# RACT 0.1.1 - Trust and tooling
