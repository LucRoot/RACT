from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from dataclasses import dataclass, field
from typing import Dict, List

from rootact.manager import Plan


@dataclass
class ResultLogger:
    """Simple deterministic logger for execution results."""

    _records: List[Dict[str, str]] = field(default_factory=list)

    def log(self, plan: Plan) -> None:
        """Record a plan's summary into internal state."""
        if plan is None:
            return
        record = {
            "assumption": plan.assumption,
            "confidence": str(plan.confidence),
            "step_count": str(len(plan.steps)),
        }
        self._records.append(record)

    def get_logs(self) -> List[Dict[str, str]]:
        """Return a copy of all recorded logs."""
        return list(self._records)

    def clear(self) -> None:
        """Reset the internal record store."""
        self._records.clear()

    def write_to_file(self, path: str) -> None:
        """Write the current logs as JSON to the given file path."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._records, f, indent=2)

    def read_from_file(self, path: str) -> None:
        """Load logs from a JSON file, replacing current records."""
        with open(path, "r", encoding="utf-8") as f:
            self._records = json.load(f)

    def __len__(self) -> int:
        return len(self._records)

    def __bool__(self) -> bool:
        return bool(self._records)
