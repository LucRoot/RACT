from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ract.manager import Plan
from ract.token_budget import TokenBudget


class MemoryArenaError(Exception):
    """Raised when memory arena persistence fails."""


@dataclass(frozen=True)
class MemoryRecord:
    """A single memory entry in the arena."""

    category: str
    content: str
    importance: int = 1
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class MemoryArena:
    """A lightweight arena for tracking long-horizon session state.

    The arena stores facts, decisions, constraints, and plan summaries that
    should survive context compression.  Before a new plan is generated the
    harness replays the highest-value memories into the prompt; after a run
    the harness records what happened so future runs can build on it.
    """

    _records: Dict[str, List[Any]] = field(default_factory=dict)
    _counter: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._counter = 0

    def _next_id(self) -> str:
        """Generate a deterministic unique identifier."""
        nid = f"mem_{self._counter}"
        self._counter += 1
        return nid

    def record(
        self,
        category: str,
        content: str,
        importance: int = 1,
        key: Optional[str] = None,
    ) -> str:
        """Store an arbitrary memory entry.

        *category* groups the entry (e.g. ``plan``, ``outcome``,
        ``constraint``).  *importance* is an integer; higher values are
        preferred during replay.  Returns the key under which the entry is
        stored.
        """
        if key is None:
            key = self._next_id()
        rec = MemoryRecord(category=category, content=content, importance=importance)
        self._records.setdefault(key, []).append(rec)
        return key

    def store(self, plan: Plan, key: Optional[str] = None) -> str:
        """Store a summary of the given plan under a unique key.

        If *key* is not provided, a fresh deterministic id is generated.
        The stored record contains the assumption, confidence and step count.
        """
        if key is None:
            key = self._next_id()
        record = {
            "assumption": plan.assumption,
            "confidence": str(plan.confidence),
            "step_count": str(len(plan.steps)),
        }
        self._records[key] = [record]
        return key

    def retrieve(self, key: str) -> List[Dict[str, str]]:
        """Return the stored record for *key* or an empty list if missing."""
        return self._records.get(key, [])

    def replay(self, max_entries: int = 20, max_tokens: int = 512) -> str:
        """Return a formatted memory block that fits inside *max_tokens*.

        Entries are ranked by importance (descending), then recency.  Whole
        entries are included or dropped; nothing is truncated mid-sentence.
        """
        entries: list[tuple[str, str, int, str]] = []
        for _key, recs in self._records.items():
            for rec in recs:
                if isinstance(rec, MemoryRecord):
                    entries.append(
                        (
                            rec.category,
                            rec.content,
                            rec.importance,
                            rec.timestamp,
                        )
                    )
                elif isinstance(rec, dict):
                    # Legacy plan summaries stored by ``store()``.
                    category = rec.get("category", "plan")
                    content = "; ".join(
                        f"{k}={v}" for k, v in rec.items() if k != "category"
                    )
                    entries.append((category, content, 1, ""))

        def _recency_key(ts: str) -> float:
            try:
                return datetime.fromisoformat(ts).timestamp()
            except Exception:  # noqa: BLE001
                return 0.0

        # Most important first; for equal importance, most recent first; for
        # equal recency, sort deterministically by category then content.
        entries.sort(key=lambda e: (-e[2], -_recency_key(e[3]), e[0], e[1]))
        selected = entries[:max_entries]

        budget = TokenBudget(max_tokens=max_tokens)
        header = "Memory:\n"
        if not budget.reserve(TokenBudget.estimate_tokens(header)):
            return ""

        parts: list[str] = []
        for category, content, _importance, _timestamp in selected:
            line = f"- [{category}] {content}\n"
            cost = TokenBudget.estimate_tokens(line)
            if not budget.reserve(cost):
                break
            parts.append(line)

        if not parts:
            return ""
        return header + "".join(parts)

    def save(self, path: Path | str) -> None:
        """Persist the arena to *path* as JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data: list[dict[str, Any]] = []
        for key, recs in self._records.items():
            for rec in recs:
                if isinstance(rec, MemoryRecord):
                    data.append(
                        {
                            "key": key,
                            "category": rec.category,
                            "content": rec.content,
                            "importance": rec.importance,
                            "timestamp": rec.timestamp,
                        }
                    )
                elif isinstance(rec, dict):
                    data.append({"key": key, **rec})
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            raise MemoryArenaError(
                f"Failed to save memory arena to {path}: {exc}"
            ) from exc

    @classmethod
    def load(cls, path: Path | str) -> "MemoryArena":
        """Load a persisted arena from *path*."""
        path = Path(path)
        arena = cls()
        if not path.is_file():
            return arena
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MemoryArenaError(
                f"Failed to load memory arena from {path}: {exc}"
            ) from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MemoryArenaError(
                f"Memory arena file is not valid JSON: {path}"
            ) from exc
        for item in data:
            item = dict(item)
            key = item.pop("key", None)
            if "category" in item and "content" in item:
                arena.record(
                    item["category"],
                    item["content"],
                    item.get("importance", 1),
                    key=key,
                )
            else:
                arena._records.setdefault(key or arena._next_id(), []).append(item)
        return arena

    @classmethod
    def for_session(cls, project_dir: Path | str, session_id: str) -> "MemoryArena":
        """Load or create the arena for *session_id* inside *project_dir*."""
        path = Path(project_dir) / ".ract" / "memory" / f"{session_id}.json"
        return cls.load(path)

    def clear(self) -> None:
        """Reset the arena to its initial empty state."""
        self._records.clear()
        self._counter = 0

    def __len__(self) -> int:
        return len(self._records)

    def __bool__(self) -> bool:
        return bool(self._records)


# RACT 0.1.1 - Trust and tooling
