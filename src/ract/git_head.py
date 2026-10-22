"""Read a repository's HEAD commit without starting git.

LR:: Every interactive turn asked git for HEAD (``git rev-parse``) and for
the last commit subjects (``git log``) to key caches, at 40 to 80 ms per
process start on Windows (B-036). The commit id HEAD points at can be read
from the files under ``.git`` in microseconds. This handles the common
layouts: a ``.git`` directory or a ``.git`` file pointing at a linked
worktree's directory, HEAD that is detached or names a branch, and the
branch ref loose or in ``packed-refs``. Anything else returns None, and the
caller asks git.
"""

from __future__ import annotations

import re
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def _git_dir(repo: Path) -> Path | None:
    dot_git = repo / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir: "):
            target = Path(text[len("gitdir: ") :])
            return target if target.is_absolute() else (repo / target)
    return None


def read_head(repo: Path | str) -> str | None:
    """The commit id HEAD points at, or None when it cannot be read cheaply."""
    try:
        git_dir = _git_dir(Path(repo))
        if git_dir is None:
            return None
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if _SHA.match(head):
            return head
        if not head.startswith("ref: "):
            return None
        ref = head[len("ref: ") :]
        # A linked worktree keeps its own HEAD but shares refs with the main
        # repository, named in its "commondir" file.
        common = git_dir
        commondir = git_dir / "commondir"
        if commondir.is_file():
            path = Path(commondir.read_text(encoding="utf-8").strip())
            common = path if path.is_absolute() else (git_dir / path)
        loose = common / ref
        if loose.is_file():
            value = loose.read_text(encoding="utf-8").strip()
            return value if _SHA.match(value) else None
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[1] == ref and _SHA.match(parts[0]):
                    return parts[0]
        return None
    except OSError:
        return None
