from __future__ import annotations


"""Operator Handshake Registry.

High-risk milestones never pause the loop. Instead, the MilestoneOracle returns a
"handshake" verdict, the loop continues with other work, and the milestone is
recorded here for operator review. The operator can approve, reject, or defer
each handshake after the fact.

**v0.4 substrate change (SUBSTRATE §3.5).** High-risk steps under the
transactional executor still record here — but resolution now blocks the
step's *commit* at the git layer, not just the plan-level milestone
acknowledgement. See ``ract.executor.loop.SubstrateLoop._finalize``: a
step whose ``handshake_ids`` include any pending id returns
``BLOCKED_ON_HANDSHAKE`` and leaves its worktree intact for operator
inspection; the parent snapshot does not advance and no dependent step
can commit past it. The blast radius is bounded by git.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HandshakeItem:
    """A single operator-handshake request.

    ``depends_on`` names other handshake ids whose resolution this
    handshake waits on. It is a display / diagnostic aid; the git-layer
    block enforced by ``SubstrateLoop`` reads the ``handshake_ids`` on
    each step spec and cross-references ``pending()``.
    """

    id: str
    description: str
    acceptance: str
    timestamp: str
    status: str = "pending"
    metadata: dict[str, Any] | None = None
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"pending", "approved", "rejected", "deferred"}:
            raise ValueError(f"Invalid handshake status: {self.status}")


class HandshakeRegistry:
    """Persist and manage operator handshakes for a project."""

    def __init__(self, project_dir: Path | str) -> None:
        self.project_dir = Path(project_dir)
        self.registry_path = self.project_dir / ".ract" / "handshakes.json"

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
        payload = []
        for item in items:
            raw = asdict(item)
            # asdict turns None metadata into {"metadata": None}; strip it to keep
            # the on-disk format clean and backward-compatible.
            if raw.get("metadata") is None:
                raw.pop("metadata", None)
            # An empty depends_on carries no information; strip it so v0.3
            # readers see the exact on-disk shape they expect.
            if not raw.get("depends_on"):
                raw.pop("depends_on", None)
            else:
                raw["depends_on"] = list(raw["depends_on"])
            payload.append(raw)
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def entries(self) -> list[HandshakeItem]:
        """Return all handshake items."""
        items: list[HandshakeItem] = []
        for raw in self._load():
            # ``depends_on`` is v0.4 and may be absent from v0.3 registry
            # files; normalize the deserialization so old files still load.
            raw = dict(raw)
            deps = raw.pop("depends_on", ())
            if isinstance(deps, list):
                deps = tuple(str(d) for d in deps)
            items.append(HandshakeItem(depends_on=tuple(deps), **raw))
        return items

    def pending(self) -> list[HandshakeItem]:
        """Return only pending handshake items."""
        return [item for item in self.entries() if item.status == "pending"]

    def add(
        self,
        milestone_id: str,
        description: str,
        acceptance: str,
        metadata: dict[str, Any] | None = None,
        depends_on: tuple[str, ...] = (),
    ) -> HandshakeItem:
        """Record a new pending handshake."""
        items = self.entries()
        item = HandshakeItem(
            id=milestone_id,
            description=description,
            acceptance=acceptance,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="pending",
            metadata=metadata,
            depends_on=tuple(depends_on),
        )
        items.append(item)
        self._save(items)
        return item

    # ------------------------------------------------------------------
    # v0.4: git-layer blocking
    # ------------------------------------------------------------------

    def blocks_commit(self, handshake_ids: tuple[str, ...] | list[str]) -> list[str]:
        """Return the subset of ``handshake_ids`` that are currently pending.

        A non-empty result means the caller (a ``SubstrateLoop`` step) must
        return ``BLOCKED_ON_HANDSHAKE`` rather than commit — SUBSTRATE §3.5.
        Empty result means the step is free to commit its worktree.
        """
        pending_ids = {item.id for item in self.pending()}
        return [hid for hid in handshake_ids if hid in pending_ids]

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
                    metadata=item.metadata,
                    depends_on=item.depends_on,
                )
                self._save(items)
                return items[i]
        raise KeyError(f"Handshake not found: {milestone_id}")


# RACT 0.1.1 - Trust and tooling
