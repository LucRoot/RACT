from __future__ import annotations


"""Refactor tax ledger for RACT.

The GitClear finding shows AI-generated code is refactoring legacy code 74% less
often. The refactor tax ledger makes pure feature-addition expensive: every
session must pay down debt by maintaining existing code at a configurable ratio.
If a session only adds code, it cannot declare completion until the planner
produces a refactor subtask.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RefactorLedger:
    """Track new vs. maintained lines for a session.

    LR:: AI defaults to adding files. The ledger forces the loop to either
    refactor existing code or explicitly admit debt. Override is permitted
    (and logged) because sometimes the honest task is pure addition.
    """

    project_dir: Path | None
    threshold: float = 3.0
    lines_added: int = 0
    lines_removed: int = 0
    lines_refactored: int = 0
    allow_debt_override: bool = False
    override_reason: str | None = None

    def record_file_changes(
        self, changes: dict[str, tuple[str | None, str | None]]
    ) -> None:
        """Record line deltas for a set of files.

        *changes* maps a relative file path to (old_content, new_content).
        - old_content is None: file was created.
        - new_content is None: file was deleted.
        - Both present: file was modified.
        """
        for _path, (old_content, new_content) in changes.items():
            if old_content is None and new_content is not None:
                self.lines_added += _count_lines(new_content)
            elif new_content is None and old_content is not None:
                self.lines_removed += _count_lines(old_content)
            elif old_content is not None and new_content is not None:
                old_lines = _count_lines(old_content)
                new_lines = _count_lines(new_content)
                if new_lines > old_lines:
                    self.lines_added += new_lines - old_lines
                    self.lines_refactored += old_lines
                elif new_lines < old_lines:
                    self.lines_removed += old_lines - new_lines
                    self.lines_refactored += new_lines
                else:
                    # Same line count: count as refactored to encourage touching old code.
                    self.lines_refactored += old_lines

    def allow_debt(self, reason: str) -> None:
        """Explicitly permit the session to exceed the refactor threshold."""
        self.allow_debt_override = True
        self.override_reason = reason

    @property
    def maintained_lines(self) -> int:
        """Lines removed or refactored; the "debt paid" column."""
        return self.lines_removed + self.lines_refactored

    @property
    def ratio(self) -> float:
        """New-to-maintained ratio. Returns 0.0 when no maintenance happened."""
        maintained = self.maintained_lines
        if maintained == 0:
            return 0.0 if self.lines_added == 0 else float("inf")
        return round(self.lines_added / maintained, 3)

    def is_breach(self) -> bool:
        """Return True if the session has breached the refactor tax threshold."""
        if self.allow_debt_override:
            return False
        if self.lines_added == 0:
            return False
        maintained = self.maintained_lines
        if maintained == 0:
            return True
        return (self.lines_added / maintained) > self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "lines_refactored": self.lines_refactored,
            "maintained_lines": self.maintained_lines,
            "ratio": self.ratio,
            "allow_debt_override": self.allow_debt_override,
            "override_reason": self.override_reason,
            "breach": self.is_breach(),
        }

    def save(self, session_id: str | None = None) -> Path:
        """Persist the ledger to `.ract/refactor_ledger.json`."""
        if self.project_dir is None:
            raise ValueError("Cannot save RefactorLedger without a project_dir.")
        ledger_dir = self.project_dir / ".ract"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        path = ledger_dir / "refactor_ledger.json"
        payload = {
            "session_id": session_id,
            **self.to_dict(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, project_dir: Path) -> "RefactorLedger":
        """Load the most recent ledger for the project, or return a fresh one."""
        path = project_dir / ".ract" / "refactor_ledger.json"
        if not path.is_file():
            return cls(project_dir=project_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            project_dir=project_dir,
            threshold=float(data.get("threshold", 3.0)),
            lines_added=int(data.get("lines_added", 0)),
            lines_removed=int(data.get("lines_removed", 0)),
            lines_refactored=int(data.get("lines_refactored", 0)),
            allow_debt_override=bool(data.get("allow_debt_override", False)),
            override_reason=data.get("override_reason"),
        )


def _count_lines(content: str) -> int:
    """Return the number of non-empty lines in *content*."""
    return sum(1 for line in content.splitlines() if line.strip())


# RACT 0.1.1 - Trust and tooling
