"""Keep the previous bytes of every file a turn replaces (S-026).

LR:: Until checkpoints and `/undo` exist (B-013), a turn that replaced the
wrong file had no way back unless the file was committed: uncommitted work
in it was gone. Every write into the operator's tree now saves the file's
previous bytes first, once per turn, under `.ract/undo/<turn>/<path>`.
`.ract/` is excluded from git, so the copies are never tracked. Only the
newest KEEP_TURNS folders are kept.

A turn binds a TurnBackup with ``turn(root)``; writers call
``save_before_replace(root, paths)``. Outside a turn (a library caller, a
unit test) nothing is saved.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

KEEP_TURNS = 20
UNDO_DIR = Path(".ract") / "undo"


class TurnBackup:
    """The previous versions saved during one turn."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.realpath(root))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.turn_id = f"{stamp}-{uuid.uuid4().hex[:6]}"
        self.saved: list[str] = []

    @property
    def folder(self) -> Path:
        return self.root / UNDO_DIR / self.turn_id

    def describe(self) -> str:
        """One line naming the folder, for the turn's summary."""
        n = len(self.saved)
        where = (UNDO_DIR / self.turn_id).as_posix()
        return f"previous version{'s' if n != 1 else ''} of {n} file{'s' if n != 1 else ''} saved in {where}/"

    def save(self, paths: Iterable[Path | str]) -> None:
        for path in paths:
            full = Path(os.path.realpath(self.root / path))
            try:
                rel = full.relative_to(self.root)
            except ValueError:
                continue  # a step worktree or anything else outside the tree
            key = rel.as_posix()
            if key.split("/", 1)[0] in {".git", ".ract"} or key in self.saved:
                continue
            if not full.is_file():
                continue  # a new file has no previous version
            target = self.folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(full, target)
            self.saved.append(key)


_current: ContextVar[TurnBackup | None] = ContextVar("ract_undo_backup", default=None)


def save_before_replace(root: Path | str, paths: Iterable[Path | str]) -> None:
    """Save the current bytes of *paths* (relative to *root*) for this turn."""
    backup = _current.get()
    if backup is None:
        return
    base = Path(os.path.realpath(root))
    backup.save(base / path for path in paths)


def prune(root: Path | str, keep: int = KEEP_TURNS) -> None:
    """Remove all but the newest *keep* turn folders."""
    undo = Path(root) / UNDO_DIR
    if not undo.is_dir():
        return
    folders = sorted(p for p in undo.iterdir() if p.is_dir())
    for old in folders[: max(0, len(folders) - keep)]:
        shutil.rmtree(old, ignore_errors=True)


@contextmanager
def turn(
    root: Path | str, *, announce: Callable[[str], object] | None = None
) -> Iterator[TurnBackup]:
    """Bind a TurnBackup for the turn; a nested call shares the outer one.

    The outermost call prunes old folders when the turn ends and passes the
    summary line to *announce* when anything was saved.
    """
    outer = _current.get()
    if outer is not None:
        yield outer
        return
    backup = TurnBackup(Path(root))
    token = _current.set(backup)
    try:
        yield backup
    finally:
        _current.reset(token)
        if backup.saved:
            prune(backup.root)
            if announce is not None:
                announce(backup.describe())


__all__ = ["KEEP_TURNS", "TurnBackup", "prune", "save_before_replace", "turn"]
