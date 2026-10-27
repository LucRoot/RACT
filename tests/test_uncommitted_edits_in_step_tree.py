"""Adjudication row 2: a step's tree contains the operator's uncommitted edits.

The base snapshot is a commit of the working tree (ADR-0047 D6): tracked changes
and untracked, not-ignored files are in it. So a run in a git repository does
not need a warning for uncommitted edits; the one case where files are left out
(too large, past the count, or over the time budget) already prints a notice.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ract.executor.worktree import take_snapshot


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def test_uncommitted_tracked_and_untracked_edits_are_in_the_snapshot(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("committed\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(
        repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"
    )
    (repo / "a.txt").write_text("uncommitted edit\n", encoding="utf-8")
    (repo / "b.txt").write_text("new, never added\n", encoding="utf-8")

    snap = take_snapshot(repo)

    assert _git(repo, "show", f"{snap.sha}:a.txt") == "uncommitted edit\n"
    assert _git(repo, "show", f"{snap.sha}:b.txt") == "new, never added\n"
    assert snap.left_out == ()
    assert snap.notice() == ""
