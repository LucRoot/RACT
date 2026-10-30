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
  junction, nothing may be written under ``.git`` or ``.ract`` (a write to
  ``.git/hooks`` or ``.ract/hooks`` becomes code execution later), and no
  secret-shaped file or ``ract.yaml`` is written (the model is never shown
  one, so it has no valid replacement for it);
- for ``send`` (the file's content goes into a model request): nothing under
  ``.git`` or ``.ract``, no secret-shaped name (``.env``, ``*.key`` ...) and
  no ``ract.yaml``/``ract.yml`` (it can hold literal api keys).
  ``.ract/operator.key`` and a ``.git/config`` remote URL with a token were
  reaching the provider in the step prompt before the write was refused
  (AUD-003). ``is_never_sent`` is the same rule for callers that already
  hold a path relative to the root.

Callers get a ``Rooted[Path]``; a refusal carries a hint that says what to
change. ``require_workspace_path`` raises ``WorkspacePathRefused`` instead,
for call sites that already report errors through exceptions.
"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from ract.rooted import Rooted

Purpose = Literal["read", "write", "send"]

# Directories no RACT write may touch, at any depth (``sub/.git`` is a
# submodule's git directory). Compared case-insensitively.
PROTECTED_WRITE_DIRS = frozenset({".git", ".ract"})

# File names that usually hold secrets: never sent to a model and left out
# of step snapshots. Compared case-insensitively.
SECRET_NAME_GLOBS = (".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519")

# Committed placeholder files, allowed by exact name (D-014). Blocking them
# stops a normal task (update the example file); a real key pasted into one
# is the request-body scanner's job (S-022).
ENV_TEMPLATE_NAMES = frozenset(
    {".env.example", ".env.sample", ".env.template", ".env.dist"}
)


def is_secret_shaped(path: str) -> bool:
    """True when the last component of ``path`` matches ``SECRET_NAME_GLOBS``.

    ``ENV_TEMPLATE_NAMES`` are exempt, by exact (case-sensitive) name.
    """
    name = re.split(r"[\\/]", path)[-1]
    if name in ENV_TEMPLATE_NAMES:
        return False
    folded = name.casefold()
    return any(fnmatch.fnmatchcase(folded, pattern) for pattern in SECRET_NAME_GLOBS)


# RACT's own config can hold literal api_key values.
NEVER_SENT_NAMES = frozenset({"ract.yaml", "ract.yml"})


def is_never_sent(relative_path: str) -> bool:
    """True for a root-relative path under ``.git``/``.ract``, secret-shaped, or ract.yaml."""
    parts = [p for p in re.split(r"[\\/]", relative_path) if p and p != "."]
    if any(part.casefold() in PROTECTED_WRITE_DIRS for part in parts):
        return True
    if not parts:
        return False
    return parts[-1].casefold() in NEVER_SENT_NAMES or is_secret_shaped(parts[-1])


# S-020 (AUD-014): Microsoft's list also has COM0, LPT0 and the superscript
# digits, and CONIN$, CONOUT$ and CLOCK$ open devices too.
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$", "clock$"}
    | {f"com{i}" for i in [*"0123456789", "\u00b9", "\u00b2", "\u00b3"]}
    | {f"lpt{i}" for i in [*"0123456789", "\u00b9", "\u00b2", "\u00b3"]}
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


# MAX_PATH counts the terminating NUL, so 259 characters is the longest
# path Windows opens without long-path support (BUILDER review of H1).
_WINDOWS_MAX_PATH = 260


def _too_long(length: int, what: str) -> Refusal:
    return _refuse(
        "too_long",
        f"{what} is {length} characters; Windows refuses paths of "
        f"{_WINDOWS_MAX_PATH} characters or more",
        "Use a shorter folder or file name, or move the project to a shorter folder.",
    )


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
    if windows and len(raw) >= _WINDOWS_MAX_PATH:
        return _too_long(len(raw), "the path")
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
        if _SHORT_NAME_RE.match(seg) and os.name != "nt":
            # Windows rules checked on another system: no volume to ask whether
            # the name is an alias, so the shape is refused. On Windows the
            # location check asks the volume (S-020, AUD-014).
            return _refuse(
                "short_name",
                f"the path component {seg!r} looks like an 8.3 short name",
                "Use the full file or directory name.",
            )
    return None


def _long_name(path: Path) -> str | None:
    """The last part of *path*'s long name on this Windows volume, or None."""
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    get_long = ctypes.windll.kernel32.GetLongPathNameW  # type: ignore[attr-defined]
    if not get_long(str(path), buffer, len(buffer)):
        return None
    return Path(buffer.value).name


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
                Path(root_real), rel_parts, purpose=purpose, fold=fold, windows=win
            )
            full = Path(root_real).joinpath(*rel_parts)
            # Windows measures the whole path, the project folder included.
            if refusal is None and win and len(str(full)) >= _WINDOWS_MAX_PATH:
                refusal = _too_long(len(str(full)), "the full path")
            if refusal is None:
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
    root_real: Path,
    rel_parts: tuple[str, ...],
    *,
    purpose: Purpose,
    fold: bool,
    windows: bool = False,
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
        if is_secret_shaped(rel_parts[-1]):
            # The model is never shown these files, so it cannot have a
            # valid replacement for one; the step snapshot leaves them out
            # for the same reason.
            return _refuse(
                "secret_shaped",
                f"{rel_parts[-1]!r} usually holds secrets and RACT does not write it",
                "Edit credential files yourself. Name a different file.",
            )
        if rel_parts[-1].casefold() in NEVER_SENT_NAMES:
            # A model that rewrites RACT's config could point the next run
            # at another provider; the operator edits it.
            return _refuse(
                "ract_config",
                f"{rel_parts[-1]!r} is RACT's configuration and RACT does not write it",
                "Edit ract.yaml yourself. Name a project file.",
            )
    if purpose == "send" and is_never_sent("/".join(rel_parts)):
        return _refuse(
            "never_sent",
            f"{'/'.join(rel_parts)!r} is RACT or git state, or usually holds "
            "secrets, and is never sent to a model",
            "Name a project source file. Keep credentials out of model requests.",
        )
    # Walk existing components: none may lead outside the root, and for
    # writes none may be a symlink or junction.
    current = root_real
    for i, part in enumerate(rel_parts):
        current = current / part
        if not os.path.lexists(current):
            break
        if windows and os.name == "nt" and _SHORT_NAME_RE.match(part):
            # S-020 (AUD-014): an existing name of 8.3 shape is refused only when
            # it is another name's alias; "a~1.txt" as itself is a file like any.
            long_name = _long_name(current)
            if long_name is not None and long_name.casefold() != part.casefold():
                return _refuse(
                    "short_name",
                    f"the path component {part!r} is the 8.3 short name of {long_name!r}",
                    "Use the full file or directory name.",
                )
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
    if purpose == "write" and _is_hard_linked(root_real.joinpath(*rel_parts)):
        # S-020 (AUD-015): a write goes through the shared file, which may be
        # outside the project.
        return _refuse(
            "hard_link",
            f"{'/'.join(rel_parts)!r} is a hard link (the same file has another name)",
            "RACT does not write through hard links. Copy the file to a new name first.",
        )
    return None


def _is_hard_linked(path: Path) -> bool:
    """True for an existing regular file with more than one name."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_nlink > 1


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


def on_disk_name(root: Path | str, name: str) -> str:
    """``name`` as the file system spells it (H5): the on-disk case when the file exists.

    On Windows "Readme.md" and "README.md" are one file; a report must name the
    file the disk holds. A name that does not exist, or a folder that cannot be
    listed, is returned as given.
    """
    target = Path(root) / name
    try:
        entries = list(os.scandir(target.parent))
    except OSError:
        return name  # nothing to compare with: the plan's spelling stands
    names = [entry.name for entry in entries]
    if target.name in names:
        return name  # the exact spelling exists (a case-sensitive file system)
    for found in names:
        if found.casefold() == target.name.casefold():
            return Path(name).with_name(found).as_posix()
    return name
