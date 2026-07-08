from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass, field
from typing import Any


def _step_key(step: Any) -> str:
    """Return a stable key for a Plan step."""
    action = getattr(step, "action", "")
    artifact = getattr(step, "expected_artifact", "")
    return f"{action}:{artifact}"


def _step_keys(plan: Any | None) -> set[str]:
    """Return the set of step keys for a plan."""
    if plan is None:
        return set()
    steps = getattr(plan, "steps", [])
    return {_step_key(s) for s in steps}


@dataclass
class ChangeDetector:
    """Detect added and removed steps between two plans."""

    _added: set[str] = field(default_factory=set)
    _removed: set[str] = field(default_factory=set)

    def diff(
        self, new_plan: Any | None, old_plan: Any | None
    ) -> dict[str, list[str] | set[str]]:
        """Compare two plans and return added/removed step keys."""
        new_keys = _step_keys(new_plan)
        old_keys = _step_keys(old_plan)
        self._added = new_keys - old_keys
        self._removed = old_keys - new_keys
        return {"added": sorted(self._added), "removed": sorted(self._removed)}

    def reset(self) -> None:
        """Clear any previously computed diff state."""
        self._added = set()
        self._removed = set()

    def __bool__(self) -> bool:
        """True when the detector holds a non-empty diff result."""
        return bool(self._added or self._removed)


# RACT 0.1.0 - Initial Public Release
