# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass
from typing import List

from rootact.manager import Plan


@dataclass
class PlanInspector:
    """Utility to inspect and validate a Plan for common pitfalls.

    This class provides simple checks such as ensuring that every Step
    has a non‑empty action, a valid provider hint, and a non‑empty
    expected_artifact. It is deliberately lightweight and has no external
    dependencies beyond the standard library.
    """

    def __init__(self, plan: Plan) -> None:
        self.plan = plan

    def validate(self) -> List[str]:
        """Run a set of validation checks on the stored Plan.

        Returns
            A list of error messages. An empty list indicates that the
            plan passed all checks.
        """
        errors: List[str] = []
        for step in self.plan.steps:
            if not step.action:
                errors.append(f"Step with empty action: {step}")
            if not step.provider_hint:
                errors.append(f"Step with empty provider_hint: {step}")
            if not step.expected_artifact:
                errors.append(f"Step with empty expected_artifact: {step}")
        return errors

    def summarize(self) -> str:
        """Return a concise, human‑readable summary of the plan.

        The summary includes the assumption, confidence, and a bullet list
        of steps with their key fields. This is useful for logging or
        debugging without pulling in any heavy utilities.
        """
        lines = [
            f"Assumption: {self.plan.assumption}",
            f"Confidence: {self.plan.confidence:.2f}",
        ]
        for i, step in enumerate(self.plan.steps, start=1):
            lines.append(
                f"  {i}. action={step.action}, provider_hint={step.provider_hint}, expected_artifact={step.expected_artifact}"
            )
        return "\n".join(lines)


# RACT 0.1.0 - Initial Public Release
