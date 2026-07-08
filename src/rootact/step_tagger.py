from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass, field
from typing import Dict, List

from rootact.manager import Plan


@dataclass
class StepTagger:
    """Utility to tag steps with identifiers and metadata."""

    _tag_counter: int = field(default=0, init=False)

    def __post__init__(self) -> None:
        self._tag_counter = 0

    def _next_tag(self) -> str:
        """Generate a deterministic tag and increment the counter."""
        tag = f"step_{self._tag_counter}"
        self._tag_counter += 1
        return tag

    def tag_plan(self, plan: Plan) -> Dict[str, List[Dict[str, str]]]:
        """
        Convert a Plan's steps into a tagged structure.

        Returns a dict with a single key "steps" whose value is a list of
        dictionaries, each containing the generated tag and the step's fields.
        """
        if plan is None or not plan.steps:
            return {"steps": []}
        tagged_steps = []
        for step in plan.steps:
            tag = self._next_tag()
            tagged_steps.append(
                {
                    "tag": tag,
                    "action": step.action,
                    "provider_hint": step.provider_hint,
                    "expected_artifact": step.expected_artifact,
                }
            )
        return {"steps": tagged_steps}

    def reset(self) -> None:
        """Reset the internal tag counter for reuse."""
        self._tag_counter = 0


# RACT 0.1.0 - Initial Public Release
