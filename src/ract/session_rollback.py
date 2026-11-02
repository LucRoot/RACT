from __future__ import annotations


import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from ract.workspace_state import check_state_path
from ract.workspace_path import NEVER_SENT_NAMES, is_secret_shaped, secret_kind


class SessionRollbackError(Exception):
    """Base exception for rollback failures."""


class SnapshotNotFoundError(SessionRollbackError):
    """Raised when no snapshot exists for the requested session."""


@dataclass
class Snapshot:
    """A point-in-time copy of selected project files."""

    created_at: str
    files: Dict[str, str]


def _config_bearing_reason(rel: str) -> str | None:
    """Why a snapshot entry targets operator config (B-8roll), or None.

    The names are the ``workspace_path`` rule vocabulary, so a refused entry
    is one the model-facing write path refuses too: ``ract.yaml``/``ract.yml``
    (a rewrite points the next run at another provider), secret-shaped names
    (``.env``, ``*.key``, ``*.pem`` ...), and ``.github/workflows/*``
    (executable CI configuration).
    """
    parts = [p for p in re.split(r"[\\/]", rel) if p and p != "."]
    if not parts:
        return None
    name = parts[-1]
    if name.casefold() in NEVER_SENT_NAMES:
        return "ract.yaml is RACT's configuration"
    if is_secret_shaped(name):
        kind = secret_kind(rel) or "a secret-shaped name"
        return f"{kind} is never restored from an unendorsed snapshot"
    if (
        len(parts) >= 3
        and parts[0].casefold() == ".github"
        and parts[1].casefold() == "workflows"
    ):
        return "a CI workflow is executable configuration"
    return None


class SessionRollback:
    """Capture and restore pre-execution file snapshots for a session.

    LR:: Snapshots are stored as JSON in ``.ract/snapshots`` so they are
    human-readable, diffable, and trivial to prune. Only files that already
    exist at capture time are recorded; restores silently skip missing entries.

    Provenance (B-8roll, audit round 2 seam 6): a snapshot file can also be
    shipped by a cloned repository, and a restore must not give a
    repo-supplied snapshot write access to config-bearing names (``ract.yaml``
    can point the next run at another provider, ``.env`` and secret-shaped
    names hold credentials, ``.github/workflows/*`` is executable CI
    configuration). RACT's own snapshots legitimately contain ``ract.yaml``
    (a session can include the project config the operator had at capture
    time), so the guard keys on provenance, not the name alone: a snapshot
    whose session id is known to the operator-side session store
    (``.ract/sessions/<id>.json``) was written by this installation and
    restores every entry; any other snapshot file is treated as
    repo-supplied, and each entry targeting a config-bearing name is refused,
    named in ``missing``, and skipped while the remaining entries still
    restore. When the store cannot be consulted the snapshot is treated as
    repo-supplied (fail closed); the restore still never crashes on a bad
    entry.
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.snapshot_dir = self.project_dir / ".ract" / "snapshots"
        check_state_path(self.snapshot_dir)  # B-213: never through a link
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def _snapshot_path(self, session_id: str) -> Path:
        from ract.undo_backup import require_name

        return self.snapshot_dir / f"{require_name(session_id, 'session id')}.json"

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
        check_state_path(self._snapshot_path(session_id))  # B-213: never through a link
        self._snapshot_path(session_id).write_text(
            json.dumps(asdict(snapshot), indent=2),
            encoding="utf-8",
        )
        return snapshot

    def _operator_known(self, session_id: str) -> bool:
        """True when the operator-side session store endorses *session_id*.

        B-8roll: a snapshot file under ``.ract/snapshots/`` can be shipped by
        a cloned repository. Only a session id the operator-side store
        (``.ract/sessions/``) knows is evidence this installation wrote the
        snapshot. A store that cannot be consulted (a link among ``.ract/``,
        an unreadable folder) endorses nothing: fail closed.
        """
        from ract.session_store import SessionStore

        try:
            return SessionStore(self.project_dir / ".ract" / "sessions").exists(
                session_id
            )
        except (OSError, ValueError):
            return False

    def restore(self, session_id: str) -> tuple[List[str], List[str]]:
        """Restore files from the snapshot. Returns (restored, missing).

        Entries that leave the workspace, and, for a snapshot the operator's
        session store does not endorse, entries targeting config-bearing
        names, are refused: each is named in ``missing`` and the rest still
        restores.
        """
        snapshot_path = self._snapshot_path(session_id)
        if not snapshot_path.is_file():
            raise SnapshotNotFoundError(
                f"No snapshot found for session '{session_id}'."
            )

        data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        files = data.get("files", {})
        restored: List[str] = []
        missing: List[str] = []
        operator_known = self._operator_known(session_id)

        from ract.undo_backup import check_entry

        for rel, content in files.items():
            # S-028b: the snapshot is a file in the workspace a repository
            # can ship; an entry that leaves the workspace is never written.
            if check_entry(self.project_dir, self.project_dir, rel) is not None:
                missing.append(rel)
                continue
            # B-8roll: a snapshot this installation did not write is
            # repo-supplied; it gets no write access to config-bearing names.
            if not operator_known and _config_bearing_reason(rel) is not None:
                missing.append(rel)
                continue
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


# RACT 0.1.1 - Trust and tooling
