from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass, field
from typing import List

from rootact.manager import Plan, Step


@dataclass
class OutputFormatter:
    """Utility to format plan output into a standardized string representation."""

    _indent: str = field(default="  ", init=False)

    def __post__init__(self) -> None:
        self._indent = "  "

    def _format_step(self, step: Step) -> str:
        return f"{self._indent}{step.action} ({step.provider_hint}) -> {step.expected_artifact}"

    def format_plan(self, plan: Plan) -> str:
        """
        Convert a Plan into a deterministic multi-line string.
        Empty plans yield an empty string.
        """
        if not plan.steps:
            return ""
        lines = [f"{self._indent}{plan.assumption} (confidence: {plan.confidence:.2f})"]
        for step in plan.steps:
            lines.append(self._format_step(step))
        return "\n".join(lines)

    def format_steps(self, steps: List[Step]) -> str:
        """
        Format a list of steps into a single space-separated string.
        Used for quick summaries.
        """
        if not steps:
            return ""
        formatted = [self._format_step(step) for step in steps]
        return " ".join(formatted)

    def reset_indent(self) -> None:
        """Reset internal indentation to default."""
        self._indent = "  "


# RACT 0.1.0 - Initial Public Release
