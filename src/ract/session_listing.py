"""List and look up saved sessions for the interactive session.

Session files live in the workspace, so a cloned repository can ship them.
Every id comes from a file name and passes ``require_name`` before use. A
file over the size cap is never read. Only the ``intent`` key is read, and
text from a file reaches the screen through ``safe_text``.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from ract.session_events import safe_text
from ract.undo_backup import require_name

MAX_SESSION_BYTES = 2 * 1024 * 1024
MAX_REQUEST_CHARS = 50
LIST_LIMIT = 10


@dataclass(frozen=True)
class SessionRow:
    session_id: str
    updated: float
    request: str
    unreadable: str


def sessions_dir(config: Path) -> Path:
    """The folder the run layer saves sessions to, for a config file."""
    return config.parent / ".ract" / "sessions"


def _short(text: str) -> str:
    one_line = " ".join(safe_text(text).split())
    if len(one_line) > MAX_REQUEST_CHARS:
        return one_line[:MAX_REQUEST_CHARS] + "..."
    return one_line


def _named_files(directory: Path) -> list[tuple[float, str, Path]]:
    """Valid session files, newest first. Names that fail ``require_name`` are skipped."""
    if not directory.is_dir():
        return []
    found: list[tuple[float, str, Path]] = []
    for path in directory.glob("*.json"):
        try:
            session_id = require_name(path.stem, "session id")
            if path.is_symlink() or not path.is_file():
                continue
            found.append((path.stat().st_mtime, session_id, path))
        except (ValueError, OSError):
            continue
    found.sort(reverse=True)
    return found


def _read_row(session_id: str, updated: float, path: Path) -> SessionRow:
    try:
        if path.stat().st_size > MAX_SESSION_BYTES:
            return SessionRow(session_id, updated, "", "too large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SessionRow(session_id, updated, "", "unreadable")
    intent = data.get("intent") if isinstance(data, dict) else None
    if not isinstance(intent, str):
        return SessionRow(session_id, updated, "", "unreadable")
    return SessionRow(session_id, updated, _short(intent), "")


def list_rows(directory: Path, limit: int = LIST_LIMIT) -> tuple[list[SessionRow], int]:
    """The newest ``limit`` sessions, and how many sessions exist in all."""
    files = _named_files(directory)
    rows = [_read_row(sid, mtime, path) for mtime, sid, path in files[:limit]]
    return rows, len(files)


def latest_row(directory: Path) -> SessionRow | None:
    """The newest session that can be resumed, or None."""
    for mtime, sid, path in _named_files(directory):
        row = _read_row(sid, mtime, path)
        if not row.unreadable:
            return row
    return None


def find_row(directory: Path, session_id: str) -> SessionRow | None:
    """The row for a validated session id, or None when no such file exists."""
    path = directory / f"{session_id}.json"
    if path.is_symlink() or not path.is_file():
        return None
    return _read_row(session_id, path.stat().st_mtime, path)


def closest_id(directory: Path, session_id: str) -> str | None:
    known = [sid for _, sid, _ in _named_files(directory)]
    matches = difflib.get_close_matches(session_id, known, n=1)
    return matches[0] if matches else None
