"""Keep the previous bytes of every file a turn replaces, and undo a turn (S-026, B-049).

LR:: Until checkpoints exist (B-013, gated), a turn that replaced the
wrong file had no way back unless the file was committed: uncommitted work
in it was gone. Every write into the operator's tree now saves the file's
previous bytes first, once per turn, and records the files the turn
created. When the turn ends a manifest (`manifest.json`) lists both and
the hash of each file as RACT left it. Only the newest KEEP_TURNS folders
are kept.

The folders live in the user state directory, keyed by the repository's
resolved path, never in the workspace (S-028): a cloned repository could
ship a `.ract/undo/*/manifest.json` naming `../anything`, and `/undo`
wrote outside the workspace. Every manifest entry is still validated
before use, and an entry that would leave the workspace is refused and
listed.

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
MANIFEST = "manifest.json"
# Top-level names a manifest entry may never touch.
_PROTECTED = {".git", ".ract"}


def repository_key(root: Path | str) -> str:
    """One key per repository, whatever path or link reached it."""
    return os.path.normcase(os.path.realpath(os.fspath(root)))


def turns_dir(root: Path | str) -> Path:
    """This repository's turn folders, in the user state directory."""
    from ract.core.keys import _default_state_dir

    digest = hashlib.sha256(repository_key(root).encode("utf-8")).hexdigest()[:16]
    return _default_state_dir() / "undo" / digest


_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def require_name(value: object, what: str) -> str:
    """*value* as a file-name-safe identifier, or ValueError (S-028b).

    LR:: Session ids and proposal ids become file and folder names. Read
    from a file a repository or a shared export can supply, "../x" escaped
    the store. A name is letters, digits, '.', '_' and '-', and does not
    start with '.'.
    """
    if (
        not isinstance(value, str)
        or not value
        or value.startswith(".")
        or not set(value) <= _NAME_CHARS
    ):
        raise ValueError(
            f"{value!r} is not a valid {what}: use letters, digits, '.', '_' and '-', "
            "not starting with '.'"
        )
    return value


def check_entry(root: Path, base: Path, entry: object) -> str | None:
    """Why *entry* may not be used under *base* inside *root*; None when it may.

    LR:: Manifest entries are relative paths written by RACT. Anything else
    (absolute, a drive or UNC path, a `..` or empty part, `.git`/`.ract`, or
    a path whose real location leaves *base* through a link) is refused.
    """
    if not isinstance(entry, str) or not entry.strip():
        return "not a path"
    text = entry.replace("\\", "/")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return "an absolute path"
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "a path with an empty, '.' or '..' part"
    if parts[0] in _PROTECTED:
        return f"a path under {parts[0]}/"
    real_base = Path(os.path.realpath(base))
    real = Path(os.path.realpath(base / text))
    if real != real_base and real_base not in real.parents:
        return "a path that leaves the workspace through a link"
    if real.parts and real.relative_to(real_base).parts[:1] in ((".git",), (".ract",)):
        return "a path under .git/ or .ract/"
    return None


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
        return turns_dir(self.root) / self.turn_id

    @property
    def changed(self) -> bool:
        return bool(self.saved or self.created)

    def describe(self) -> str:
        """One line naming the folder, for the turn's summary."""
        n = len(self.saved)
        return (
            f"previous version{'s' if n != 1 else ''} of {n} "
            f"file{'s' if n != 1 else ''} saved; /undo restores them"
        )

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
            "root": repository_key(self.root),
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
    """Remove all but the newest *keep* turn folders (never through a link)."""
    undo = turns_dir(root)
    if not undo.is_dir():
        return
    folders = sorted(p for p in undo.iterdir() if p.is_dir() and not p.is_symlink())
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
    refused: list[tuple[str, str]] = field(default_factory=list)
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
        out += [f"refused {entry!r}: {why}" for entry, why in self.refused]
        if not (self.restored or self.removed or self.skipped or self.refused):
            out.append(f"nothing to {verb}: the files are already as they were")
        return out


def previous_version(
    root: Path | str, backup_id: object, relative_path: object
) -> bytes | None:
    """The bytes a turn saved for *relative_path* before replacing it, or None.

    LR:: The turn summary draws a diff from these bytes (B-014b). The id and
    the path arrive in an event, so neither is trusted: the id must be a name
    (``require_name``), the folder's manifest must belong to this repository,
    the path must pass ``check_entry`` and be one the turn saved, and a saved
    file that is a link is not read. A bad id or path raises ValueError;
    a turn or file that is not there gives None. No path travels in an event.
    """
    name = require_name(backup_id, "backup id")
    base = Path(os.path.realpath(root))
    folder = turns_dir(base) / name
    problem = check_entry(base, folder, relative_path)
    if problem is not None:
        raise ValueError(f"{relative_path!r} is not a saved file: {problem}")
    assert isinstance(relative_path, str)
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # no turn of that id, or an unreadable manifest
    if not isinstance(manifest, dict) or manifest.get("root") != repository_key(base):
        return None
    key = relative_path.replace("\\", "/")
    if key not in (manifest.get("saved") or []):
        return None
    saved = folder / key
    if saved.is_symlink() or not saved.is_file():
        return None
    return saved.read_bytes()


def _manifests(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    undo = turns_dir(root)
    if not undo.is_dir():
        return []
    found = []
    key = repository_key(root)
    for folder in sorted(
        p for p in undo.iterdir() if p.is_dir() and not p.is_symlink()
    ):
        try:
            data = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a folder without a readable manifest
        if not isinstance(data, dict) or data.get("root") != key:
            continue  # recorded for another repository
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
    result = UndoResult(folder=str(folder))
    after_raw = data.get("after")
    after: dict[str, Any] = after_raw if isinstance(after_raw, dict) else {}
    saved_raw = data.get("saved")
    created_raw = data.get("created")
    saved = (
        [p for p in saved_raw if isinstance(p, str)]
        if isinstance(saved_raw, list)
        else []
    )
    created = (
        [p for p in created_raw if isinstance(p, str)]
        if isinstance(created_raw, list)
        else []
    )
    for raw_list in (saved_raw, created_raw):
        for raw in raw_list if isinstance(raw_list, list) else []:
            if not isinstance(raw, str):
                result.refused.append((repr(raw), "not a path"))
    with turn(root, kind=new_kind) as backup:
        for path in [*saved, *created]:
            # S-028: --force skips the hash check, never this one.
            why = check_entry(root, root, path)
            if why is None and path in saved:
                why = check_entry(root, folder, path)
            if why is not None:
                result.refused.append((path, why))
                continue
            full = root / path
            if not force and _sha256(full) != after.get(path):
                result.skipped.append(path)
                continue
            backup.save([full])
            if path in saved:
                full.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(folder / path, full)
                result.restored.append(path)
            elif full.exists():
                full.unlink()
                result.removed.append(path)
    # A skipped or refused entry keeps the turn pending: --force can reach a
    # skipped file, and a refusal is reported again on the next /undo.
    if not result.skipped and not result.refused:
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
    "check_entry",
    "require_name",
    "repository_key",
    "turns_dir",
    "TurnBackup",
    "UndoResult",
    "prune",
    "redo",
    "save_before_replace",
    "turn",
    "undo",
]
