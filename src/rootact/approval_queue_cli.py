# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"


class _RootKnotType:
    """Sentinel for Root Knot default arguments."""


_ROOT_KNOT: _RootKnotType = _RootKnotType()

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


@dataclass
class ApprovalQueueCLI:
    pending: List[dict[str, Any]] = field(default_factory=list)
    decisions: dict[str, str] = field(default_factory=dict)

    def __init__(
        self, queue: Optional[List[dict[str, Any]]] | _RootKnotType = _ROOT_KNOT
    ) -> None:
        if isinstance(queue, _RootKnotType):
            resolved: Optional[List[dict[str, Any]]] = None
        else:
            resolved = queue
        self.pending = list(resolved) if resolved is not None else []
        self.decisions = {}

    def list(self) -> List[dict[str, Any]]:
        return [
            {"index": i, "summary": item.get("summary", str(item))}
            for i, item in enumerate(self.pending)
        ]

    def approve(self, index: int) -> None:
        if 0 <= index < len(self.pending):
            item = self.pending.pop(index)
            key = item.get("id", str(id(item)))
            self.decisions[key] = "approved"

    def reject(self, index: int) -> None:
        if 0 <= index < len(self.pending):
            item = self.pending.pop(index)
            key = item.get("id", str(id(item)))
            self.decisions[key] = "rejected"

    def prompt(self, action: str) -> bool:
        """Return True if the action is approved; subclasses may override."""
        return self.decisions.get(action) == "approved"

    def persist(self, path: str = "approval_decisions.json") -> None:
        data = {"pending": self.pending, "decisions": self.decisions}
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str = "approval_decisions.json") -> "ApprovalQueueCLI":
        try:
            raw = json.loads(Path(path).read_text())
            pending = raw.get("pending", [])
            decisions = raw.get("decisions", {})
            instance = cls(queue=pending)
            instance.decisions = decisions
            return instance
        except FileNotFoundError:
            return cls()
