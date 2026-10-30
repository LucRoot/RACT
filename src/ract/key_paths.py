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
import sys
from pathlib import Path

_WARNED: set[str] = set()


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
    """Say once per path that a key was read from its old place inside the project."""
    key = str(path)
    if key in _WARNED:
        return
    _WARNED.add(key)
    print(
        f"warning: read a key from {path}, inside the project; `ract policy "
        "migrate-keys` moves it out (the old place stops being read after this release)",
        file=sys.stderr,
        flush=True,
    )


def migrate(workspace_root: Path | str) -> list[str]:
    """Move the project's keys out of ``.ract/``; one line per file moved or left.

    A target that already exists with other bytes is left alone and named:
    nothing is overwritten.
    """
    import shutil

    root = Path(workspace_root)
    moves: list[tuple[Path, Path]] = []
    legacy_recompile = root / ".ract" / "operator.key"
    if legacy_recompile.is_file():
        moves.append((legacy_recompile, recompile_key_path()))
    for kind in ("sandbox", "alm"):
        old = root / ".ract" / kind
        if not old.is_dir():
            continue
        for path in sorted(old.rglob("*.key")):
            moves.append((path, repo_key_dir(root, kind) / path.relative_to(old)))
    lines: list[str] = []
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


__all__ = ["legacy_read", "migrate", "recompile_key_path", "repo_key_dir"]
