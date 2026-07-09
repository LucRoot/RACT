# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Task-aware temperature routing for provider calls.

RootAct uses lower temperatures when the model must produce deterministic,
correct code, and slightly higher temperatures when it should explore or plan.
The router is keyword-driven so it works with any provider without changing
adapter code.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TemperatureRouter:
    """Return a temperature value based on task description keywords."""

    code_temp: float = 0.15
    plan_temp: float = 0.4
    default_temp: float = 0.25
    brainstorm_temp: float = 0.55
    _code_keywords: tuple[str, ...] = field(
        default=(
            "write",
            "generate",
            "implement",
            "refactor",
            "fix",
            "repair",
            "edit",
            "apply",
            "create",
            "update",
            "patch",
        ),
        repr=False,
    )
    _plan_keywords: tuple[str, ...] = field(
        default=(
            "plan",
            "design",
            "architect",
            "milestone",
            "backlog",
            "structure",
            "outline",
        ),
        repr=False,
    )
    _brainstorm_keywords: tuple[str, ...] = field(
        default=(
            "brainstorm",
            "ideate",
            "explore",
            "generate ideas",
            "propose",
            " alternatives",
        ),
        repr=False,
    )

    def for_action(self, action: str) -> float:
        """Pick a temperature for an executor step action."""
        text = action.lower()
        if any(keyword in text for keyword in self._brainstorm_keywords):
            return self.brainstorm_temp
        if any(keyword in text for keyword in self._code_keywords):
            return self.code_temp
        if any(keyword in text for keyword in self._plan_keywords):
            return self.plan_temp
        return self.default_temp

    def for_plan(self, intent: str) -> float:
        """Pick a temperature for the management LM planning call."""
        text = intent.lower()
        if any(keyword in text for keyword in self._brainstorm_keywords):
            return self.brainstorm_temp
        if any(keyword in text for keyword in self._plan_keywords):
            return self.plan_temp
        # Most loop intents ask for code changes; planning is still closer to
        # structured reasoning than pure generation, so use default/plan temp.
        return self.plan_temp


# RACT 0.1.1 - Trust and tooling
