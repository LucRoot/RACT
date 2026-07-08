# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

_ROOT_KNOT = object()


class SessionRollbackError(Exception):
    """Base exception for rollback failures."""


class SnapshotNotFoundError(SessionRollbackError):
    """Raised when no snapshot exists for the requested session."""


@dataclass
class Snapshot:
    """A point-in-time copy of selected project files."""

    created_at: str
    files: Dict[str, str]


class SessionRollback:
    """Capture and restore pre-execution file snapshots for a session.

    LR:: Snapshots are stored as JSON in ``.rootact/snapshots`` so they are
    human-readable, diffable, and trivial to prune. Only files that already
    exist at capture time are recorded; restores silently skip missing entries.
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.snapshot_dir = self.project_dir / ".rootact" / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def _snapshot_path(self, session_id: str) -> Path:
        return self.snapshot_dir / f"{session_id}.json"

    def capture(self, session_id: str, file_paths: List[Path]) -> Snapshot:
        """Record the current contents of *file_paths* for later restoration."""
        files: Dict[str, str] = {}
        for file_path in file_paths:
            resolved = Path(file_path).resolve()
            try:
                rel = resolved.relative_to(self.project_dir.resolve()).as_posix()
            except ValueError:
                # Files outside the project directory are ignored; they are not
                # ours to roll back.
                continue
            if resolved.is_file():
                files[rel] = resolved.read_text(encoding="utf-8")

        snapshot = Snapshot(
            created_at=datetime.now(timezone.utc).isoformat(),
            files=files,
        )
        self._snapshot_path(session_id).write_text(
            json.dumps(asdict(snapshot), indent=2),
            encoding="utf-8",
        )
        return snapshot

    def restore(self, session_id: str) -> tuple[List[str], List[str]]:
        """Restore files from the snapshot. Returns (restored, missing)."""
        snapshot_path = self._snapshot_path(session_id)
        if not snapshot_path.is_file():
            raise SnapshotNotFoundError(
                f"No snapshot found for session '{session_id}'."
            )

        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        files = data.get("files", {})
        restored: List[str] = []
        missing: List[str] = []

        for rel, content in files.items():
            target = self.project_dir / rel
            if target.is_file() or not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                restored.append(rel)
            else:
                missing.append(rel)

        return restored, missing

    def snapshot_exists(self, session_id: str) -> bool:
        """Return True if a snapshot has been captured for *session_id*."""
        return self._snapshot_path(session_id).is_file()

    def list_snapshots(self) -> List[str]:
        """Return all session IDs that have a stored snapshot."""
        return [p.stem for p in self.snapshot_dir.glob("*.json") if p.is_file()]
