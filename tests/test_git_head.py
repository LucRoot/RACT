"""ract.git_head reads HEAD without starting git (B-036)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ract.git_head import read_head

GIT = ["git", "-c", "user.name=d", "-c", "user.email=d@example.invalid"]


def _repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    (path / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run([*GIT, "add", "-A"], cwd=path, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "c"], cwd=path, check=True)
    return path


def _rev_parse(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_branch_loose_detached_and_packed(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    assert read_head(repo) == _rev_parse(repo)
    subprocess.run(["git", "pack-refs", "--all"], cwd=repo, check=True)
    assert read_head(repo) == _rev_parse(repo)  # ref now only in packed-refs
    subprocess.run(["git", "checkout", "-q", "--detach"], cwd=repo, check=True)
    assert read_head(repo) == _rev_parse(repo)


def test_linked_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "side", str(linked)],
        cwd=repo,
        check=True,
    )
    assert read_head(linked) == _rev_parse(linked)


def test_not_a_repository_or_unborn(tmp_path: Path) -> None:
    assert read_head(tmp_path) is None
    unborn = tmp_path / "u"
    unborn.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=unborn, check=True)
    assert read_head(unborn) is None
