"""B-138: the needs_repository and needs_history markers read the checkout correctly.

The cases are the ones WRIGHT's Linux run met: a full repository, a depth-1
clone (CI), a plain folder, and a copied worktree whose ``.git`` file names a
path git cannot open. The clone is of a local temporary repository; nothing
is downloaded.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.repository_state import FULL, NONE, SHALLOW, skip_reason, state_of


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=d",
            "-c",
            "user.email=d@example.invalid",
            "-c",
            "protocol.file.allow=always",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def full(tmp_path: Path) -> Path:
    repo = tmp_path / "full"
    repo.mkdir()
    _git(repo, "init", "-q")
    for n in (1, 2):
        (repo / "a.txt").write_text(f"{n}\n", encoding="utf-8")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-q", "-m", f"c{n}")
    _git(repo, "tag", "v0.0.1", "HEAD~1")
    return repo


def test_a_repository_with_its_history_is_full(full: Path) -> None:
    assert state_of(full) == FULL


def test_a_depth_1_clone_is_shallow(full: Path, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", "--depth", "1", full.as_uri(), str(clone))
    assert state_of(clone) == SHALLOW


def test_a_plain_folder_is_none(tmp_path: Path) -> None:
    folder = tmp_path / "plain"
    folder.mkdir()
    assert state_of(folder) == NONE


def test_a_copied_worktree_whose_git_file_names_nothing_is_none(tmp_path: Path) -> None:
    # B-046: the copy's .git named C:/RootClaw/RACT/.git/worktrees/b046 inside WSL.
    folder = tmp_path / "copy"
    folder.mkdir()
    (folder / ".git").write_text(
        f"gitdir: {tmp_path / 'gone' / 'worktrees' / 'b046'}\n", encoding="utf-8"
    )
    assert state_of(folder) == NONE


@pytest.mark.parametrize(
    ("marker", "state", "skipped"),
    [
        ("needs_repository", FULL, False),
        ("needs_repository", SHALLOW, False),
        ("needs_repository", NONE, True),
        ("needs_history", FULL, False),
        ("needs_history", SHALLOW, True),
        ("needs_history", NONE, True),
    ],
)
def test_each_marker_skips_only_where_its_need_is_missing(
    marker: str, state: str, skipped: bool
) -> None:
    reason = skip_reason(marker, state)
    assert (reason is not None) is skipped
    if reason:
        assert "needs" in reason  # the skip says why
