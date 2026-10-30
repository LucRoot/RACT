"""Tier-2 answers for one session: once, or for the rest of this session (ADR-0047 D6).

LR:: A tier-2 write (a control or executable-configuration file) asks the
operator at the console. "s" allows writes to the same files for the rest of
the session, and that allowance lives only in this process's memory: it is
never read back from disk, so ``/resume`` and a new process start with none
(ADR-0048 D6, the resume rule). What is written to disk is only the fact
that the session once allowed a path, in the user state directory keyed by
repository and session id, never in the project. When a resumed session
reaches such a path again, the question says why it is asked again:
"approvals from session <id> do not carry over". A cloned repository cannot
ship that record, and the record never answers a question.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# session id -> the paths allowed for the session in this process.
_LIVE: dict[str, set[str]] = {}


def _record_path(root: Path | str, session_id: str) -> Path:
    from ract import undo_backup
    from ract.core.keys import _default_state_dir

    name = undo_backup.require_name(session_id, "session id")
    key = undo_backup.repository_key(root)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return _default_state_dir() / "tier2" / digest / f"{name}.json"


def recorded(root: Path | str, session_id: str) -> set[str]:
    """The paths this session allowed in an earlier process. Facts only."""
    try:
        path = _record_path(root, session_id)
        if not path.is_file():
            return set()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[tier2 approvals] could not read the record: {exc}", flush=True)
        return set()
    return {p for p in data if isinstance(p, str)} if isinstance(data, list) else set()


def _record(root: Path | str, session_id: str, paths: set[str]) -> None:
    try:
        path = _record_path(root, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = sorted(recorded(root, session_id) | paths)
        path.write_text(json.dumps(merged), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"[tier2 approvals] could not write the record: {exc}", flush=True)


def forget(session_id: str) -> None:
    """Drop this process's allowances for *session_id* (``/resume`` switches)."""
    _LIVE.pop(session_id, None)


class SessionApprovals:
    """The tier-2 question for one session, with "allow for this session" in memory."""

    def __init__(self, root: Path | str, session_id: str | None, ask: Any) -> None:
        self.root = Path(root)
        self.session_id = session_id
        # ask(name, args, note) -> "once" | "session" | "deny"
        self.ask = ask

    def __call__(self, name: str, args: Any) -> bool:
        from ract.tools.write import targets

        paths = set(targets(name, args))
        live = _LIVE.setdefault(self.session_id, set()) if self.session_id else set()
        if paths and paths <= live:
            return True
        note = ""
        if self.session_id and paths & recorded(self.root, self.session_id):
            note = f"approvals from session {self.session_id} do not carry over"
        answer = self.ask(name, args, note)
        if answer == "session" and self.session_id:
            live.update(paths)
            _record(self.root, self.session_id, paths)
        return answer in {"once", "session"}


__all__ = ["SessionApprovals", "forget", "recorded"]
