from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from dataclasses import dataclass
from typing import Dict

from rootact.manager import Plan, Step

_ROOT_KNOT = object()


@dataclass
class ChangeSummary:
    """
    Summarize planned or executed file changes between two snapshots.
    """

    old: Dict[str, str]
    new: Dict[str, str]

    def __init__(self, old: Dict[str, str], new: Dict[str, str]) -> None:
        self.old = old
        self.new = new

    def summarize(self) -> str:
        """
        Return a concise, human-readable paragraph describing added,
        removed, and modified file counts.
        """
        added = set(self.new) - set(self.old)
        removed = set(self.old) - set(self.new)
        common = set(self.old) & set(self.new)
        modified = {name for name in common if self.old[name] != self.new[name]}

        if not added and not removed and not modified:
            return "No changes detected."

        parts: list[str] = []
        if added:
            parts.append(f"added {len(added)} file(s)")
        if removed:
            parts.append(f"removed {len(removed)} file(s)")
        if modified:
            parts.append(f"modified {len(modified)} file(s)")

        summary = ", ".join(parts)
        return f"Changes: {summary}."


_plan = Plan(
    assumption="change_summary_generator must produce a concise summary of added, removed, and modified files",
    confidence=0.95,
    steps=[
        Step(
            action="create ChangeSummary class with summarize method",
            provider_hint="internal",
            expected_artifact="src/rootact/change_summary_generator.py",
        )
    ],
)
# RACT 0.1.1 - Trust and Tooling
