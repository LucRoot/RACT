# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Planner for RootAct.

The planner is intentionally thin in the MVP. It delegates plan generation to the
management LM and validates that the returned plan is non-empty and internally
consistent. Future versions may add counterfactual pruning and dependency graphs.
"""

from rootact.manager import Manager, Plan
from rootact.rooted import Rooted


class Planner:
    """Produces a validated plan for a user intent."""

    def __init__(self, manager: Manager) -> None:
        self.manager = manager

    def plan(self, intent: str) -> Rooted[Plan]:
        """Generate and validate a plan."""
        plan_rooted = self.manager.plan(intent)
        if not plan_rooted.is_ok():
            return plan_rooted.with_step("planner.validate")

        plan = plan_rooted.unwrap()
        if not plan.steps:
            return Rooted(
                value=None,
                assumption="The management LM produces at least one actionable step.",
                confidence=0.0,
                provenance=["planner.validate"],
                error="Plan contains no steps.",
            )

        return Rooted(
            value=plan,
            assumption=plan.assumption,
            confidence=plan.confidence,
            provenance=["planner.validate"],
        )


# RACT 0.1.1 - Trust and tooling
