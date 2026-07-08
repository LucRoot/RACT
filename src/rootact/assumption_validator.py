from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Assumption:
    description: str
    confidence: float


@dataclass
class ValidationResult:
    assumption: Assumption
    is_valid: bool
    reason: str


class AssumptionValidator:
    def __init__(self) -> None:
        self._ROOT_KNOT = _ROOT_KNOT

    def validate(self, assumption: Assumption) -> ValidationResult:
        """Validate an assumption based on its confidence and description."""
        if assumption.confidence < 0.0 or assumption.confidence > 1.0:
            return ValidationResult(
                assumption=assumption,
                is_valid=False,
                reason="Confidence must be between 0.0 and 1.0",
            )
        if not assumption.description.strip():
            return ValidationResult(
                assumption=assumption,
                is_valid=False,
                reason="Description cannot be empty",
            )
        return ValidationResult(
            assumption=assumption,
            is_valid=True,
            reason="Assumption passes basic sanity checks",
        )

    def validate_many(self, assumptions: List[Assumption]) -> List[ValidationResult]:
        return [self.validate(assumption) for assumption in assumptions]

    def to_json(self, result: ValidationResult) -> str:
        return json.dumps(
            {
                "assumption": {
                    "description": result.assumption.description,
                    "confidence": result.assumption.confidence,
                },
                "is_valid": result.is_valid,
                "reason": result.reason,
            }
        )

    @staticmethod
    def from_json(data: dict) -> "AssumptionValidator":
        # No mutable state to reconstruct; returns a singleton.
        return AssumptionValidator()


# Expose the sentinel for tests to import

__all__ = ["Assumption", "ValidationResult", "AssumptionValidator", "_ROOT_KNOT"]

# Root knot sentinel for optional arguments
# RACT 0.1.0 - Initial Public Release
