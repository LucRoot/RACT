"""Where RACT keeps keys: outside every workspace (B-111, ADR-0048 R3).

LR:: A key inside the project is a key a repository, a tool or a backup can
carry away, and a model that reads the tree could be shown it. The sandbox
and ALM verifier keys now live in the user state directory, one folder per
repository (keyed by its resolved path, like the undo folders); the
intent-recompile key lives with the operator key in the user config
directory. The old locations inside ``.ract/`` stay readable for this
release with a warning on stderr, and ``ract policy migrate-keys`` moves
them out.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from pathlib import Path

from ract.git_run import run_git

_WARNED: set[str] = set()
# FILE_ATTRIBUTE_REPARSE_POINT: a junction, a symbolic link or another redirect.
_REPARSE_POINT = 0x400


def repo_key_dir(workspace_root: Path | str, kind: str) -> Path:
    """``<state>/keys/<repository digest>/<kind>`` for a project's run keys."""
    from ract.core.keys import _default_state_dir

    real = os.path.normcase(os.path.realpath(os.fspath(workspace_root)))
    digest = hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]
    return _default_state_dir() / "keys" / digest / kind


def recompile_key_path() -> Path:
    """The intent-recompile key, next to the operator key in the user config."""
    from ract.policy import config_dir

    return config_dir() / "operator" / "recompile.key"


def legacy_read(path: Path) -> None:
    """Say, every time, that a key was read from its old place inside the project (W3)."""
    _WARNED.add(str(path))
    print(
        f"warning: read a key from {path}, inside the project; `ract policy "
        "migrate-keys` moves it out (the old place stops being read after this release)",
        file=sys.stderr,
        flush=True,
    )


def _is_link(path: Path) -> bool:
    """A symbolic link, or on Windows any reparse point: a junction needs no privilege."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _linked(path: Path, root: Path) -> bool:
    """True when *path* or a folder between it and the project's ``.ract`` is a link."""
    stop = root / ".ract"
    current = path
    while True:
        if _is_link(current):
            return True
        if current == stop or current.parent == current:
            return False
        current = current.parent


def _tracked(path: Path, root: Path) -> bool:
    """True when git tracks *path* in the repository at *root* (W3)."""
    import subprocess

    try:
        done = run_git(
            # B-206: run_git turns fsmonitor and the operator's hooks off.
            "ls-files",
            "--error-unmatch",
            "--",
            path.relative_to(root).as_posix(),
            cwd=root,
            capture_output=True,
            timeout=10,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"[keys] git could not say whether {path} is tracked: {exc}", flush=True)
        return True
    return done.returncode == 0


def legacy_key(path: Path, workspace_root: Path | str) -> Path | None:
    """*path*, a key at its old place inside the project, when it may be read (W3).

    Only a regular file that is not a link (nor under one), that git does not
    track, and (on POSIX) that the current user owns: a key a repository ships
    makes no verdict. The warning is printed every time the old place is read.
    """
    root = Path(workspace_root)
    if not path.exists() and not path.is_symlink():
        return None
    why = ""
    if _linked(path, root):
        why = "it is a link"
    elif not path.is_file():
        why = "it is not a regular file"
    elif sys.platform != "win32" and path.stat().st_uid != os.getuid():
        why = "another user owns it"
    elif _tracked(path, root):
        why = "the repository tracks it"
    if why:
        print(
            f"warning: did not read the key at {path}, inside the project: {why}",
            file=sys.stderr,
            flush=True,
        )
        return None
    legacy_read(path)
    return path


def migrate(workspace_root: Path | str) -> list[str]:
    """Move the project's keys out of ``.ract/``; one line per file moved or left.

    A target that already exists with other bytes is left alone and named:
    nothing is overwritten. A link (the file, or a folder on the way under
    ``.ract``) and anything but a regular file is skipped and named (W2).
    """
    import shutil

    root = Path(workspace_root)
    moves: list[tuple[Path, Path]] = []
    lines: list[str] = []
    legacy_recompile = root / ".ract" / "operator.key"
    if _linked(legacy_recompile, root):
        lines.append(f"skipped {legacy_recompile}: it is a link")
    elif legacy_recompile.is_file():
        moves.append((legacy_recompile, recompile_key_path()))
    for kind in ("sandbox", "alm"):
        old = root / ".ract" / kind
        if _linked(old, root):
            lines.append(f"skipped {old}: it is a link")
            continue
        if not old.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(old, followlinks=False):
            here = Path(dirpath)
            for name in sorted(dirnames):
                if _is_link(here / name):
                    lines.append(f"skipped {here / name}: it is a link")
            dirnames[:] = sorted(d for d in dirnames if not _is_link(here / d))
            for name in sorted(filenames):
                path = here / name
                if not name.endswith(".key"):
                    continue
                if _is_link(path):
                    lines.append(f"skipped {path}: it is a link")
                elif not path.is_file():
                    lines.append(f"skipped {path}: it is not a regular file")
                else:
                    moves.append(
                        (path, repo_key_dir(root, kind) / path.relative_to(old))
                    )
    for source, target in moves:
        if target.exists() and target.read_bytes() != source.read_bytes():
            lines.append(f"left {source}: {target} already holds another key")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            target.parent.chmod(0o700)
        shutil.move(str(source), str(target))
        lines.append(f"moved {source} to {target}")
    return lines


__all__ = ["legacy_key", "legacy_read", "migrate", "recompile_key_path", "repo_key_dir"]
