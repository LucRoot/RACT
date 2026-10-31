"""B-138: what kind of git checkout the tests run in, for the needs_* markers.

A test that reads this repository's own history (its tags, the commits a
document cites) cannot pass in a shallow clone, which CI starts from, or in a
copied tree with no repository at all (WRIGHT's Linux run, B-046: the copy's
``.git`` named a Windows worktree, so every git command exited 128). Such a
test is marked, and skipped with the reason when its need is not met:

- ``needs_repository``: a git work tree that git can open;
- ``needs_history``: that, and not shallow (the tags and old commits exist).
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

FULL = "full"
SHALLOW = "shallow"
NONE = "none"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        stdin=subprocess.DEVNULL,
    )


def state_of(root: Path) -> str:
    """``full``, ``shallow`` or ``none`` (git cannot open a work tree at *root*)."""
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return NONE
    shallow = _git(root, "rev-parse", "--is-shallow-repository")
    if shallow.returncode != 0:
        return NONE
    return SHALLOW if shallow.stdout.strip() == "true" else FULL


@lru_cache(maxsize=1)
def this_repository() -> str:
    return state_of(REPO)


def skip_reason(marker: str, state: str) -> str | None:
    """Why a test with *marker* is skipped in a checkout in *state*, or None."""
    if marker == "needs_repository" and state == NONE:
        return "needs a git checkout of this repository (git cannot open one here)"
    if marker == "needs_history" and state != FULL:
        return "needs this repository's full history and tags; this checkout is " + (
            "a shallow clone" if state == SHALLOW else "not a git repository"
        )
    return None
