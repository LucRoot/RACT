"""Per-run session memory for the four function contracts.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Function
contracts. Every function reads the previous function's output; the
:class:`SessionMemory` holds the running record and persists to
``evals/runs/<run_id>/session.json`` after every write.

The store is intentionally file-based (not SQLite): the four
contracts are small structured records, one per run; a JSON file is
readable by ``jq`` and diffable in a PR review. Module_09 wires the
watcher-invalidation callback if the assembly pipeline needs one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.functions.contracts import (
    CandidateDiff,
    ChangePlan,
    ResearchBundle,
    WorkOrder,
    from_json,
    to_json,
)


@dataclass
class SessionMemory:
    """A per-run container for the four function outputs.

    Constructed empty; each function's setter (:meth:`set_work_order`
    etc.) persists the full record to ``session_path`` after the
    write. A reader can rehydrate from disk via
    :meth:`from_path`.
    """

    session_path: Path
    work_order: WorkOrder | None = None
    research_bundle: ResearchBundle | None = None
    change_plan: ChangePlan | None = None
    candidate_diff: CandidateDiff | None = None

    def set_work_order(self, work_order: WorkOrder) -> None:
        self.work_order = work_order
        self._persist()

    def set_research_bundle(self, research_bundle: ResearchBundle) -> None:
        self.research_bundle = research_bundle
        self._persist()

    def set_change_plan(self, change_plan: ChangePlan) -> None:
        self.change_plan = change_plan
        self._persist()

    def set_candidate_diff(self, candidate_diff: CandidateDiff) -> None:
        self.candidate_diff = candidate_diff
        self._persist()

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-serialisable payload for this session."""
        return {
            "work_order": to_json(self.work_order) if self.work_order else None,
            "research_bundle": (
                to_json(self.research_bundle) if self.research_bundle else None
            ),
            "change_plan": (to_json(self.change_plan) if self.change_plan else None),
            "candidate_diff": (
                to_json(self.candidate_diff) if self.candidate_diff else None
            ),
        }

    def _persist(self) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(
            json.dumps(self.to_payload(), sort_keys=True, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def from_path(cls, path: Path) -> "SessionMemory":
        """Rehydrate a SessionMemory from the on-disk JSON."""
        if not path.is_file():
            return cls(session_path=path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        session = cls(session_path=path)
        if payload.get("work_order"):
            session.work_order = from_json(payload["work_order"])
        if payload.get("research_bundle"):
            session.research_bundle = from_json(payload["research_bundle"])
        if payload.get("change_plan"):
            session.change_plan = from_json(payload["change_plan"])
        if payload.get("candidate_diff"):
            session.candidate_diff = from_json(payload["candidate_diff"])
        return session


__all__ = ["SessionMemory"]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
