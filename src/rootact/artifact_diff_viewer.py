from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import difflib
from dataclasses import dataclass
from typing import Dict, List

from rootact.manager import Plan, Step

_ROOT_KNOT = object()


@dataclass
class DiffViewer:
    """
    Simple diff viewer that renders changes between two file snapshots.
    """

    old: Dict[str, str]
    new: Dict[str, str]

    def __init__(self, old: Dict[str, str], new: Dict[str, str]) -> None:
        self.old = old
        self.new = new

    def render(self) -> str:
        """
        Render a human‑readable diff.

        * Files present only in ``new`` are listed under "Added".
        * Files present only in ``old`` are listed under "Removed".
        * For files that exist in both, a line‑level diff is shown using
          ``difflib.unified_diff``.
        * Unchanged files are omitted.

        Returns
        -------
        str
            A non‑empty string containing the formatted summary.
        """
        lines: List[str] = []

        # Added files
        added = set(self.new) - set(self.old)
        if added:
            lines.append("Added:\n" + "\n".join(sorted(added)) + "\n")

        # Removed files
        removed = set(self.old) - set(self.new)
        if removed:
            lines.append("Removed:\n" + "\n".join(sorted(removed)) + "\n")

        # Changed files – show unified diff for each
        changed = set(self.old) & set(self.new) - added - removed
        for fname in sorted(changed):
            old_content = self.old[fname]
            new_content = self.new[fname]
            diff = difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=fname,
                tofile=fname,
                lineterm="",
            )
            diff_lines = list(diff)
            if diff_lines:
                # Drop the header lines that refer to the filename; keep them for context
                header = [
                    line
                    for line in diff_lines[:2]
                    if line.startswith("---") or line.startswith("+++")
                ]
                lines.extend(header + diff_lines[2:])
        return "".join(lines) or "No changes detected."


_plan = Plan(
    assumption="artifact_diff_viewer must render added, removed, and line-level diffs for changed files",
    confidence=0.95,
    steps=[
        Step(
            action="create DiffViewer class with register method",
            provider_hint="internal",
            expected_artifact="src/rootact/artifact_diff_viewer.py",
        )
    ],
)
# RACT 0.1.0 - Initial Public Release
