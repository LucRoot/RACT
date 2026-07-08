# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass

from .manager import Plan


@dataclass
class ValidationResult:
    is_valid: bool
    message: str


@dataclass
class PlanValidator:
    """Simple validator for RootACT plans."""

    @staticmethod
    def validate(plan: Plan) -> ValidationResult:
        """Validate a plan based on basic heuristics."""
        if not plan.assumption:
            return ValidationResult(False, "Plan assumption is empty.")
        if plan.confidence < 0.0 or plan.confidence > 1.0:
            return ValidationResult(False, f"Invalid confidence: {plan.confidence}")
        if not plan.steps:
            return ValidationResult(False, "Plan must contain at least one step.")
        for step in plan.steps:
            if not step.action:
                return ValidationResult(False, "Step action cannot be empty.")
            if not step.expected_artifact:
                return ValidationResult(
                    False, "Step expected_artifact cannot be empty."
                )
        return ValidationResult(True, "Plan is valid.")
