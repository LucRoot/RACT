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
# previous_version never loads a saved file larger than this (G-141).
MAX_PREVIOUS_VERSION_BYTES = 8 * 1024 * 1024
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
    S-036: a NUL character is refused (it crashed the write that followed),
    and on Windows so are a `:` stream suffix (an alternate data stream
    hides data inside a file) and device names such as `con` or `aux.txt`.
    Those two are legal file names elsewhere, so only Windows refuses them.
    """
    if not isinstance(entry, str) or not entry.strip():
        return "not a path"
    if "\x00" in entry:
        return "a path with a NUL character"
    text = entry.replace("\\", "/")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return "an absolute path"
    if os.name == "nt" and ":" in text:
        return "a name with a ':' stream suffix"
    parts = text.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "a path with an empty, '.' or '..' part"
    if parts[0] in _PROTECTED:
        return f"a path under {parts[0]}/"
    if os.name == "nt" and any(_is_device_name(part) for part in parts):
        return "a Windows device name"
    real_base = Path(os.path.realpath(base))
    real = Path(os.path.realpath(base / text))
    if real != real_base and real_base not in real.parents:
        return "a path that leaves the workspace through a link"
    if real.parts and real.relative_to(real_base).parts[:1] in ((".git",), (".ract",)):
        return "a path under .git/ or .ract/"
    return None


_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{kind}{n}" for kind in ("COM", "LPT") for n in "123456789\u00b9\u00b2\u00b3"}
)


def _is_device_name(part: str) -> bool:
    """True for a Windows device name, with or without an extension (``aux.txt``)."""
    return part.split(".")[0].rstrip(" ").upper() in _DEVICE_NAMES


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
        # The base snapshot commit of each step applied in this turn, kept
        # under refs/ract/checkpoints/<turn_id>/<n> (B-110 D6).
        self.bases: list[str] = []

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
            # Once per step for the run's checkpoint (D13), before the
            # once-per-turn check: a later step needs its own copy.
            from ract import run_checkpoint

            run_checkpoint.note_saving(self, key, full)
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
            "bases": self.bases,
            "done": False,
        }
        (self.folder / MANIFEST).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )


_current: ContextVar[TurnBackup | None] = ContextVar("ract_undo_backup", default=None)


def current_backup_id() -> str | None:
    """The id of the turn backup bound now, or None outside a turn."""
    backup = _current.get()
    return backup.turn_id if backup is not None else None


def keep_base(root: Path | str, commit: str) -> None:
    """Keep a step's base snapshot as this turn's checkpoint (B-110 D6).

    Outside a turn nothing is kept, as for the saved copies.
    """
    backup = _current.get()
    if backup is None or not commit:
        return
    from ract.executor.worktree import keep_checkpoint_ref

    if keep_checkpoint_ref(Path(root), backup.turn_id, len(backup.bases) + 1, commit):
        backup.bases.append(commit)


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
        try:
            data = json.loads((old / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict) and data.get("bases"):
            from ract.executor.worktree import drop_checkpoint_refs

            drop_checkpoint_refs(Path(root), old.name)
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
    if saved.stat().st_size > MAX_PREVIOUS_VERSION_BYTES:
        return None  # too large to draw; the summary shows counts only
    return saved.read_bytes()


def note_reviewed(root: Path | str, turn_id: object, relative_path: object) -> None:
    """Record *relative_path* as ``/review`` left it, so ``/undo`` still restores it (B-014c).

    LR:: ``/undo`` skips a file whose contents differ from what the turn
    wrote (the user edited it since). A file rewritten by ``/review`` is
    not such an edit: its hash in the turn's manifest is updated, and the
    saved copy, which is what ``/undo`` restores, is not touched. The id and
    the path are checked as ``previous_version`` checks them; the path must
    be one the turn saved or created. A bad id or path raises ValueError.
    """
    name = require_name(turn_id, "turn id")
    base = Path(os.path.realpath(root))
    folder = turns_dir(base) / name
    problem = check_entry(base, base, relative_path)
    if problem is not None:
        raise ValueError(f"{relative_path!r} is not a project file: {problem}")
    assert isinstance(relative_path, str)
    manifest_path = folder / MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"turn {name} has no readable manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("root") != repository_key(base):
        raise ValueError(f"turn {name} belongs to another repository")
    key = relative_path.replace("\\", "/")
    if key not in _names(manifest.get("saved")) + _names(manifest.get("created")):
        raise ValueError(f"turn {name} did not change {key!r}")
    after = manifest.get("after")
    after = after if isinstance(after, dict) else {}
    after[key] = _sha256(base / key)
    manifest["after"] = after
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _stamp_time(turn_id: str) -> str:
    """The local time a turn id was made, as ``YYYY-MM-DD HH:MM``, or "" when unreadable."""
    try:
        made = datetime.strptime(turn_id.split("-", 1)[0], "%Y%m%dT%H%M%S%fZ")
    except ValueError:
        return ""
    return made.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _names(value: object) -> list[str]:
    return [p for p in value if isinstance(p, str)] if isinstance(value, list) else []


def checkpoints(root: Path | str) -> list[dict[str, Any]]:
    """Each saved turn of this repository, newest first (B-085, ``/undo list``).

    Each row: ``turn`` (the folder's name), ``time``, ``kind`` (turn, undo or
    redo), ``saved`` and ``created`` (relative paths), ``done`` (undone).
    Only folders whose manifest names this repository are listed.
    """
    base = Path(os.path.realpath(root))
    rows = [
        {
            "turn": folder.name,
            "time": _stamp_time(folder.name),
            "kind": str(data.get("kind") or "turn"),
            "saved": _names(data.get("saved")),
            "created": _names(data.get("created")),
            "done": bool(data.get("done")),
        }
        for folder, data in _manifests(base)
    ]
    rows.reverse()
    return rows


def last_turn_changes(
    root: Path | str,
) -> tuple[str | None, list[tuple[str, str | None, str | None]], list[str]]:
    """The last turn's files as ``(path, before, after)``, and a note per file that cannot be shown.

    LR:: ``/diff`` (B-085) draws these with the turn summary's renderer.
    ``before`` comes from the turn's saved copy through ``previous_version``
    (every check it makes applies); ``after`` is the file now, or None when it
    is gone. A path from a manifest is not trusted: one that fails
    ``check_entry`` is a note, never a read.
    """
    base = Path(os.path.realpath(root))
    turns = [
        row for row in checkpoints(base) if row["kind"] == "turn" and not row["done"]
    ]
    if not turns:
        return None, [], []
    last = turns[0]
    changes: list[tuple[str, str | None, str | None]] = []
    notes: list[str] = []

    def now(key: str) -> str | None:
        target = base / key
        if target.is_symlink() or not target.is_file():
            return None
        return target.read_bytes().decode("utf-8", errors="replace")

    for key in [*last["saved"], *last["created"]]:
        if check_entry(base, base, key) is not None:
            notes.append(f"diff not available for {key}")
            continue
        before: str | None = None
        if key in last["saved"]:
            try:
                saved = previous_version(base, last["turn"], key)
            except ValueError:
                saved = None
            if saved is None:
                notes.append(f"diff not available for {key}")
                continue
            before = saved.decode("utf-8", errors="replace")
        changes.append((key, before, now(key)))
    return last["turn"], changes, notes


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


def restore(
    root: Path | str, turn_id: object, *, force: bool = False
) -> list[UndoResult]:
    """Go back to checkpoint *turn_id*: reverse every later turn, newest first (B-110 D6).

    LR:: ``/restore`` is ``/undo`` repeated with the same rule for each turn:
    a file is put back only while it still has the digest RACT left, and one
    the operator changed since is skipped and named. The walk stops at the
    first turn that keeps a skipped or refused file, so an older turn is never
    reversed under a newer one that is still in place; ``--force`` reaches a
    skipped file as ``/undo --force`` does. The checkpoint itself is kept:
    its files stay as that turn left them. Each reversal is an undo, so
    ``/redo`` brings the latest one back. An id that names no checkpoint of
    this repository is refused.
    """
    base = Path(os.path.realpath(root))
    target = require_name(turn_id, "checkpoint")
    known = {folder.name for folder, _data in _manifests(base)}
    if target not in known:
        raise ValueError(f"no checkpoint {target!r} is recorded for this repository")
    results: list[UndoResult] = []
    while True:
        pending = [
            folder.name
            for folder, data in _manifests(base)
            if data.get("kind") in {"turn", "redo"} and not data.get("done")
        ]
        if not pending or pending[-1] <= target:
            return results
        result = _reverse(base, {"turn", "redo"}, "undo", force)
        results.append(result)
        if result.skipped or result.refused:
            return results


__all__ = [
    "KEEP_TURNS",
    "check_entry",
    "current_backup_id",
    "keep_base",
    "require_name",
    "repository_key",
    "turns_dir",
    "TurnBackup",
    "UndoResult",
    "prune",
    "redo",
    "restore",
    "save_before_replace",
    "turn",
    "undo",
]
