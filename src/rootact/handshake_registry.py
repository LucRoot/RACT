# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Operator Handshake Registry.

High-risk milestones never pause the loop. Instead, the MilestoneOracle returns a
"handshake" verdict, the loop continues with other work, and the milestone is
recorded here for operator review. The operator can approve, reject, or defer
each handshake after the fact.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HandshakeItem:
    """A single operator-handshake request."""

    id: str
    description: str
    acceptance: str
    timestamp: str
    status: str = "pending"

    def __post_init__(self) -> None:
        if self.status not in {"pending", "approved", "rejected", "deferred"}:
            raise ValueError(f"Invalid handshake status: {self.status}")


class HandshakeRegistry:
    """Persist and manage operator handshakes for a project."""

    def __init__(self, project_dir: Path | str) -> None:
        self.project_dir = Path(project_dir)
        self.registry_path = self.project_dir / ".rootact" / "handshakes.json"

    def _load(self) -> list[dict[str, Any]]:
        if not self.registry_path.is_file():
            return []
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return data

    def _save(self, items: list[HandshakeItem]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(item) for item in items]
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def entries(self) -> list[HandshakeItem]:
        """Return all handshake items."""
        return [HandshakeItem(**raw) for raw in self._load()]

    def pending(self) -> list[HandshakeItem]:
        """Return only pending handshake items."""
        return [item for item in self.entries() if item.status == "pending"]

    def add(
        self, milestone_id: str, description: str, acceptance: str
    ) -> HandshakeItem:
        """Record a new pending handshake."""
        items = self.entries()
        item = HandshakeItem(
            id=milestone_id,
            description=description,
            acceptance=acceptance,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="pending",
        )
        items.append(item)
        self._save(items)
        return item

    def update_status(self, milestone_id: str, status: str) -> HandshakeItem:
        """Approve, reject, or defer a handshake by milestone id."""
        if status not in {"approved", "rejected", "deferred"}:
            raise ValueError(f"Invalid status transition: {status}")
        items = self.entries()
        for i, item in enumerate(items):
            if item.id == milestone_id:
                items[i] = HandshakeItem(
                    id=item.id,
                    description=item.description,
                    acceptance=item.acceptance,
                    timestamp=item.timestamp,
                    status=status,
                )
                self._save(items)
                return items[i]
        raise KeyError(f"Handshake not found: {milestone_id}")


# RACT 0.1.1 - Trust and Tooling
