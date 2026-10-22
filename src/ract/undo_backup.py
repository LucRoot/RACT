"""Keep the previous bytes of every file a turn replaces, and undo a turn (S-026, B-049).

LR:: Until checkpoints exist (B-013, gated), a turn that replaced the
wrong file had no way back unless the file was committed: uncommitted work
in it was gone. Every write into the operator's tree now saves the file's
previous bytes first, once per turn, under `.ract/undo/<turn>/<path>`,
and records the files the turn created. When the turn ends a manifest
(`manifest.json`) lists both and the hash of each file as RACT left it.
`.ract/` is excluded from git, so the copies are never tracked. Only the
newest KEEP_TURNS folders are kept.

`/undo` (B-049) uses the latest turn's folder: it restores what the turn
replaced and removes what it created, skipping any file changed since the
turn unless forced. It does this through the same mechanism, so the undo
has its own folder and `/redo` reverses it once.

A turn binds a TurnBackup with ``turn(root)``; writers call
``save_before_replace(root, paths)``. Outside a turn (a library caller, a
unit test) nothing is saved.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

KEEP_TURNS = 20
UNDO_DIR = Path(".ract") / "undo"
MANIFEST = "manifest.json"


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


class TurnBackup:
    """The previous versions saved, and the files created, during one turn."""

    def __init__(self, root: Path, kind: str = "turn") -> None:
        self.root = Path(os.path.realpath(root))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.turn_id = f"{stamp}-{uuid.uuid4().hex[:6]}"
        self.kind = kind
        self.saved: list[str] = []
        self.created: list[str] = []

    @property
    def folder(self) -> Path:
        return self.root / UNDO_DIR / self.turn_id

    @property
    def changed(self) -> bool:
        return bool(self.saved or self.created)

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
            if key.split("/", 1)[0] in {".git", ".ract"}:
                continue
            if key in self.saved or key in self.created:
                continue
            if not full.is_file():
                # A new file has no previous version; undo removes it.
                self.created.append(key)
                continue
            target = self.folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(full, target)
            self.saved.append(key)

    def finish(self) -> None:
        """Write the manifest: what was saved, created, and left by RACT."""
        if not self.changed:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        manifest = {
            "kind": self.kind,
            "turn": self.turn_id,
            "saved": self.saved,
            "created": self.created,
            "after": {p: _sha256(self.root / p) for p in [*self.saved, *self.created]},
            "done": False,
        }
        (self.folder / MANIFEST).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )


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
    root: Path | str,
    *,
    announce: Callable[[str], object] | None = None,
    kind: str = "turn",
) -> Iterator[TurnBackup]:
    """Bind a TurnBackup for the turn; a nested call shares the outer one.

    The outermost call writes the manifest and prunes old folders when the
    turn ends, and passes the summary line to *announce* when anything was
    saved.
    """
    outer = _current.get()
    if outer is not None:
        yield outer
        return
    backup = TurnBackup(Path(root), kind)
    token = _current.set(backup)
    try:
        yield backup
    finally:
        _current.reset(token)
        if backup.changed:
            backup.finish()
            prune(backup.root)
            if backup.saved and announce is not None:
                announce(backup.describe())


# ------------------------------------------------------------------ undo


@dataclass
class UndoResult:
    restored: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    folder: str | None = None

    def lines(self, verb: str) -> list[str]:
        if self.folder is None:
            return [f"nothing to {verb}: no turn RACT can reverse is recorded here"]
        out = [f"restored {p}" for p in self.restored]
        out += [f"removed {p} (the turn created it)" for p in self.removed]
        out += [
            f"skipped {p}: it changed after RACT wrote it; /{verb} --force overwrites it"
            for p in self.skipped
        ]
        if not (self.restored or self.removed or self.skipped):
            out.append(f"nothing to {verb}: the files are already as they were")
        return out


def _manifests(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    undo = root / UNDO_DIR
    if not undo.is_dir():
        return []
    found = []
    for folder in sorted(p for p in undo.iterdir() if p.is_dir()):
        try:
            data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a folder from before manifests existed
        found.append((folder, data))
    return found


def _reverse(root: Path, kinds: set[str], new_kind: str, force: bool) -> UndoResult:
    root = Path(os.path.realpath(root))
    candidates = [
        (folder, data)
        for folder, data in _manifests(root)
        if data.get("kind") in kinds and not data.get("done")
    ]
    if not candidates:
        return UndoResult()
    folder, data = candidates[-1]
    result = UndoResult(folder=(UNDO_DIR / folder.name).as_posix() + "/")
    after: dict[str, str | None] = data.get("after") or {}
    with turn(root, kind=new_kind) as backup:
        for path in [*data.get("saved", []), *data.get("created", [])]:
            full = root / path
            if not force and _sha256(full) != after.get(path):
                result.skipped.append(path)
                continue
            backup.save([full])
            if path in data.get("saved", []):
                full.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(folder / path, full)
                result.restored.append(path)
            elif full.exists():
                full.unlink()
                result.removed.append(path)
    # A skipped file keeps the turn pending, so `--force` can still reach it.
    if not result.skipped:
        data["done"] = True
        (folder / MANIFEST).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return result


def undo(root: Path | str, *, force: bool = False) -> UndoResult:
    """Reverse the latest turn (or redo) not yet reversed."""
    return _reverse(Path(root), {"turn", "redo"}, "undo", force)


def redo(root: Path | str, *, force: bool = False) -> UndoResult:
    """Reverse the latest undo not yet reversed."""
    return _reverse(Path(root), {"undo"}, "redo", force)


__all__ = [
    "KEEP_TURNS",
    "TurnBackup",
    "UndoResult",
    "prune",
    "redo",
    "save_before_replace",
    "turn",
    "undo",
]
