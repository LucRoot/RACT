"""Resolve a path argument to a file inside the workspace, or refuse it.

LR:: Paths reach RACT from places the operator does not control: a model's
``expected_artifact``, the headers of a model-written diff, and, from v0.6,
tool-call arguments. Before this module each caller joined the string onto the
project directory itself. ``DiffApplier`` accepted ``../`` and absolute paths
from diff headers, and ``Executor._write_artifact`` refused absolute paths but
not ``..``, so a model could write outside the project. Every such path now
goes through ``resolve_workspace_path`` (ADR-0047 D2).

The checks run on the string first, before the disk is touched, and then on
the resolved location:

- refused outright: empty paths, NUL and other control characters, any ``..``
  segment (even one that would land inside the root), and ``/proc/*/root`` or
  ``/proc/*/cwd`` style synonyms;
- on Windows: drive-relative paths (``C:foo``), UNC and device paths
  (``\\\\server\\share``, ``\\\\?\\``, ``\\\\.\\``), reserved device names
  (``CON``, ``NUL``, ``COM1`` ...), alternate data streams (``name:stream``),
  components ending in a dot or space, and 8.3 short names (``GIT~1``);
- absolute paths are accepted only when they point inside the root;
- the deepest existing ancestor is resolved with ``realpath`` (which follows
  symlinks and Windows junctions) and must stay inside the resolved root;
- for writes: no existing component inside the root may be a symlink or a
  junction, and nothing may be written under ``.git`` or ``.ract`` (a write
  to ``.git/hooks`` or ``.ract/hooks`` becomes code execution later).

Callers get a ``Rooted[Path]``; a refusal carries a hint that says what to
change. ``require_workspace_path`` raises ``WorkspacePathRefused`` instead,
for call sites that already report errors through exceptions.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from ract.rooted import Rooted

Purpose = Literal["read", "write"]

# Directories no RACT write may touch, at any depth (``sub/.git`` is a
# submodule's git directory). Compared case-insensitively.
PROTECTED_WRITE_DIRS = frozenset({".git", ".ract"})

_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_SHORT_NAME_RE = re.compile(r"^[^~]{1,6}~\d+(\.[^.]{0,3})?$")
_PROC_RE = re.compile(r"^/proc/[^/]+/(root|cwd)(/|$)")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class Refusal:
    """Why a path was refused."""

    code: str
    message: str
    hint: str


class WorkspacePathRefused(ValueError):
    """Raised by ``require_workspace_path`` when a path is refused."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(refusal.message)
        self.refusal = refusal


def _refuse(code: str, message: str, hint: str) -> Refusal:
    return Refusal(code, message, hint)


def _string_checks(raw: str, *, windows: bool) -> Refusal | None:
    if not raw or not raw.strip():
        return _refuse("empty", "the path is empty", "Name a file inside the project.")
    if any(ord(ch) < 32 or ch == "\x7f" for ch in raw):
        return _refuse(
            "control_character",
            "the path contains a NUL or control character",
            "Remove control characters from the path.",
        )
    segments = re.split(r"[\\/]", raw)
    if any(seg == ".." for seg in segments):
        return _refuse(
            "parent_segment",
            f"the path {raw!r} contains '..'",
            "Use a path relative to the project root without '..'.",
        )
    if _PROC_RE.match(raw.replace("\\", "/")):
        return _refuse(
            "proc_synonym",
            f"the path {raw!r} names another process's root or working directory",
            "Use a path relative to the project root.",
        )
    if not windows:
        return None
    pure = PureWindowsPath(raw)
    if raw.startswith(("\\\\", "//")):
        return _refuse(
            "unc_or_device",
            f"the path {raw!r} is a UNC or device path",
            "Use a path relative to the project root.",
        )
    if pure.drive and not pure.root:
        return _refuse(
            "drive_relative",
            f"the path {raw!r} is relative to a drive, not to the project",
            "Use a path relative to the project root.",
        )
    for seg in segments:
        if not seg or seg == "." or (pure.drive and seg == pure.drive):
            continue
        if ":" in seg:
            return _refuse(
                "alternate_data_stream",
                f"the path component {seg!r} names an alternate data stream",
                "Remove ':' from the file name.",
            )
        if seg != seg.rstrip(" ."):
            return _refuse(
                "trailing_dot_or_space",
                f"the path component {seg!r} ends in a dot or space, which Windows drops",
                "Remove the trailing dot or space.",
            )
        if seg.split(".")[0].strip().lower() in _WINDOWS_RESERVED:
            return _refuse(
                "reserved_device_name",
                f"the path component {seg!r} is a Windows device name",
                "Choose a different file name.",
            )
        if _SHORT_NAME_RE.match(seg):
            return _refuse(
                "short_name",
                f"the path component {seg!r} looks like an 8.3 short name",
                "Use the full file or directory name.",
            )
    return None


def _is_link_or_junction(path: Path) -> bool:
    if os.path.islink(path):
        return True
    try:
        st = os.lstat(path)
    except OSError:
        return False
    attributes = getattr(st, "st_file_attributes", 0)
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _same_or_inside(child: str, parent: str, *, fold: bool) -> bool:
    if fold:
        child, parent = child.casefold(), parent.casefold()
    parent = parent.rstrip("\\/")
    return (
        child == parent
        or child.startswith(parent + os.sep)
        or child.startswith(parent + "/")
    )


def resolve_workspace_path(
    root: Path | str,
    user_path: str | os.PathLike[str],
    *,
    purpose: Purpose = "read",
    windows: bool | None = None,
) -> Rooted[Path]:
    """Return the absolute path inside ``root`` that ``user_path`` names.

    ``windows`` selects the Windows string rules; it defaults to the current
    platform so tests can exercise both rule sets anywhere.
    """
    win = (os.name == "nt") if windows is None else windows
    fold = win or sys.platform == "darwin"
    raw = os.fspath(user_path)
    refusal = _string_checks(raw, windows=win)
    if refusal is None:
        root_real = os.path.realpath(os.fspath(root))
        candidate = Path(raw)
        is_abs = (
            candidate.is_absolute()
            or PurePosixPath(raw.replace("\\", "/")).is_absolute()
        )
        if is_abs:
            target_str = os.path.realpath(raw)
            if not _same_or_inside(target_str, root_real, fold=fold):
                refusal = _refuse(
                    "outside_root",
                    f"the absolute path {raw!r} is outside the project",
                    "Use a path inside the project, relative to its root.",
                )
            else:
                rel_parts = Path(os.path.relpath(target_str, root_real)).parts
        else:
            rel_parts = tuple(p for p in re.split(r"[\\/]", raw) if p and p != ".")
        if refusal is None:
            refusal = _location_checks(
                Path(root_real), rel_parts, purpose=purpose, fold=fold
            )
            if refusal is None:
                full = Path(root_real).joinpath(*rel_parts)
                return Rooted(
                    value=full,
                    assumption=f"{raw!r} names a location inside the project root.",
                    confidence=1.0,
                    provenance=["workspace_path.resolve", f"purpose:{purpose}"],
                )
    assert refusal is not None
    return Rooted(
        value=None,
        assumption=f"{raw!r} names a location inside the project root.",
        confidence=0.0,
        provenance=["workspace_path.resolve", f"refused:{refusal.code}"],
        error=f"path refused: {refusal.message}",
        hint=refusal.hint,
    )


def _location_checks(
    root_real: Path, rel_parts: tuple[str, ...], *, purpose: Purpose, fold: bool
) -> Refusal | None:
    if not rel_parts:
        return _refuse(
            "is_root",
            "the path is the project root itself",
            "Name a file inside the project.",
        )
    if purpose == "write":
        for part in rel_parts:
            if part.casefold() in PROTECTED_WRITE_DIRS:
                return _refuse(
                    "protected_directory",
                    f"writes under {part!r} are not allowed",
                    f"RACT never writes into {part}/. Choose a path outside it.",
                )
    # Walk existing components: none may lead outside the root, and for
    # writes none may be a symlink or junction.
    current = root_real
    for i, part in enumerate(rel_parts):
        current = current / part
        if not os.path.lexists(current):
            break
        if purpose == "write" and _is_link_or_junction(current):
            return _refuse(
                "symlink_in_path",
                f"{'/'.join(rel_parts[: i + 1])!r} is a symlink or junction",
                "RACT does not write through links. Write to the real path.",
            )
        resolved = os.path.realpath(current)
        if not _same_or_inside(resolved, str(root_real), fold=fold):
            return _refuse(
                "escapes_root",
                f"{'/'.join(rel_parts[: i + 1])!r} resolves outside the project",
                "The path leads out of the project through a link. Use a path inside it.",
            )
    return None


def require_workspace_path(
    root: Path | str,
    user_path: str | os.PathLike[str],
    *,
    purpose: Purpose = "read",
    windows: bool | None = None,
) -> Path:
    """Like ``resolve_workspace_path`` but raises ``WorkspacePathRefused``."""
    result = resolve_workspace_path(root, user_path, purpose=purpose, windows=windows)
    if result.value is None:
        code = result.provenance[-1].removeprefix("refused:")
        message = (result.error or "").removeprefix("path refused: ")
        raise WorkspacePathRefused(Refusal(code, message, result.hint or ""))
    return result.value
