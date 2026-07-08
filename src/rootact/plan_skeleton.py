from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import field
from typing import List

from rootact.manager import Plan, Step


class PlanSkeleton:
    """A lightweight utility that builds a minimal Plan from a simple description.

    It is deterministic, stateless, and uses only the standard library and the
    frozen ``Plan``/``Step`` dataclasses from ``rootact.manager``.
    """

    def __init__(
        self, assumption: str, confidence: float, steps: List[Step] | None = None
    ):
        self.assumption = assumption
        self.confidence = confidence
        self.steps = field(default_factory=list) if steps is None else steps

    @staticmethod
    def from_simple(description: str, confidence: float = 0.9) -> "PlanSkeleton":
        """Create a PlanSkeleton from a one‑sentence description.

        Args:
            description: A brief textual description of the desired plan.
            confidence: Confidence level for the generated plan (default 0.9).

        Returns:
            A new ``PlanSkeleton`` instance with a single step that mirrors the
            description.
        """
        if not description:
            raise ValueError("description must not be empty")
        step = Step(
            action=description.strip(),
            provider_hint="default",
            expected_artifact="plan_output",
        )
        return PlanSkeleton(assumption=description, confidence=confidence, steps=[step])

    def as_plan(self) -> Plan:
        """Convert the skeleton into an immutable ``Plan`` instance.

        The conversion copies the stored assumption and confidence and uses the
        internal steps.  Because ``Plan`` and ``Step`` are frozen, the resulting
        object is safe to share.
        """
        return Plan(
            assumption=self.assumption,
            confidence=self.confidence,
            steps=self.steps,
        )


# Simple sanity check when run as a script
if __name__ == "__main__":
    skeleton = PlanSkeleton.from_simple("Deploy application", 0.95)
    plan = skeleton.as_plan()
    print(f"Generated plan: {plan}")
# RACT 0.1.0 - Initial Public Release
