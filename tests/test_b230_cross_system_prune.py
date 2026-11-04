"""B-230: RACT never drops a worktree registration the other system made.

A repository used from Windows and WSL records each worktree in the form of
the system that made it; from the other side it looks dead, and a bare
``git worktree prune`` dropped it (the B-216). ``prune_dead_own`` drops
only RACT's own dead registrations in this system's form. The registrations
here are written by hand (the path text simulates the other system); no
worktree is created. the lane runs the same file in WSL.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ract.executor.worktree import other_system_path, prune_dead_own

WINDOWS_FORM = "C:/Users/op/proj/.git/ract-worktrees/{name}/.git"
POSIX_FORM = "/home/op/proj/.git/ract-worktrees/{name}/.git"
OTHER_FORM = POSIX_FORM if os.name == "nt" else WINDOWS_FORM


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".git" / "worktrees").mkdir()
    (root / ".git" / "ract-worktrees").mkdir()
    return root


def _register(repo: Path, name: str, gitdir: str, *, locked: bool = False) -> Path:
    admin = repo / ".git" / "worktrees" / name
    admin.mkdir()
    (admin / "gitdir").write_text(gitdir + "\n", encoding="utf-8")
    if locked:
        (admin / "locked").write_text("in use\n", encoding="utf-8")
    return admin


def test_the_other_system_form_is_recognised() -> None:
    assert other_system_path(OTHER_FORM.format(name="w"))
    here = str(Path.cwd() / "x")
    assert not other_system_path(here)


def test_a_registration_the_other_system_made_is_never_dropped(repo: Path) -> None:
    other = _register(repo, "w-other", OTHER_FORM.format(name="w-other"))
    assert prune_dead_own(repo) == []
    assert other.is_dir()


def test_only_rACTs_own_dead_registration_in_this_form_is_dropped(repo: Path) -> None:
    own_root = Path(os.path.realpath(repo / ".git" / "ract-worktrees"))
    dead = _register(repo, "w-dead", (own_root / "w-dead" / ".git").as_posix())
    alive_folder = own_root / "w-alive"
    alive_folder.mkdir()
    alive = _register(repo, "w-alive", (alive_folder / ".git").as_posix())
    locked = _register(
        repo, "w-locked", (own_root / "w-locked" / ".git").as_posix(), locked=True
    )
    operators = _register(
        repo, "w-mine", (repo.parent / "elsewhere" / ".git").as_posix()
    )

    assert prune_dead_own(repo) == ["w-dead"]
    assert not dead.exists()
    assert alive.is_dir() and locked.is_dir() and operators.is_dir()
