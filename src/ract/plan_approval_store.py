"""Plan approvals a run remembers for a resumed session (ADR-0049 D12, L-196 point 3).

The store is in the user state directory, keyed by repository and session id, like the run
checkpoints and the handshake marks. It is not in the project: a cloned repository cannot ship
an approval, so a planted session file never skips the question. Each entry maps the hash of a
plan the operator approved to the step numbers the operator skipped (L-196 point 2).
"""

from __future__ import annotations

import hashlib
import json

from ract.atomic_write import write_atomic
from pathlib import Path


def _approvals_dir(root: Path | str) -> Path:
    from ract import undo_backup
    from ract.core.keys import _default_state_dir

    key = undo_backup.repository_key(root)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return _default_state_dir() / "approvals" / digest


def approvals_path(root: Path | str, session_id: str) -> Path:
    """The approval file for *session_id* in this repository; ValueError when the id is not a name."""
    from ract import undo_backup

    name = undo_backup.require_name(session_id, "session id")
    return _approvals_dir(root) / f"{name}.json"


def load(root: Path | str, session_id: str) -> dict[str, list[int]]:
    """The approved plans of this session: plan hash -> skipped step numbers. Empty when none or unreadable."""
    try:
        path = approvals_path(root, session_id)
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[plan approvals] could not read the saved approvals: {exc}", flush=True)
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(digest): [int(n) for n in skipped]
        for digest, skipped in data.items()
        if isinstance(skipped, list)
    }


def remember(
    root: Path | str, session_id: str, digest: str, skipped: list[int]
) -> None:
    """Record that the operator approved the plan *digest*, skipping *skipped*."""
    approved = load(root, session_id)
    approved[digest] = sorted(skipped)
    path = approvals_path(root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # B-224: a fresh temporary file, never the predictable ".json.tmp" name.
    write_atomic(path, json.dumps(approved).encode("utf-8"))
