"""_fast_forward_head soft vs hard reset -- unit tests (module_05).

v0.5.1 wiring module_05 (Lens C C-04 closure). The pre-fix loop
called ``git reset --hard`` unconditionally at commit boundary,
which destroyed the working-tree state the compensator's
``mode="soft"`` invariant was designed to preserve. The fix routes
through ``git reset --soft`` when a compensator is about to be
installed; the legacy ``--hard`` path is retained under an explicit
``soft=False`` flag for callers that want the tree scrubbed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ract.executor.loop import _fast_forward_head


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _run(*argv: str, cwd: Path) -> str:
    result = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True,
        check=True, env=_env(),
    )
    return result.stdout.strip()


def _init(root: Path) -> tuple[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    _run("git", "init", "-q", "-b", "main", cwd=root)
    (root / "a.txt").write_text("seed", encoding="utf-8")
    _run("git", "add", "-A", cwd=root)
    _run("git", "commit", "-q", "-m", "seed", cwd=root)
    initial = _run("git", "rev-parse", "HEAD", cwd=root)
    # Second commit: touch a.txt.
    (root / "a.txt").write_text("second", encoding="utf-8")
    _run("git", "add", "-A", cwd=root)
    _run("git", "commit", "-q", "-m", "second", cwd=root)
    after = _run("git", "rev-parse", "HEAD", cwd=root)
    # Reset back to initial so we can fast-forward to `after`.
    _run("git", "reset", "--hard", initial, cwd=root)
    return initial, after


# ---------------------------------------------------------------------------
# Soft path -- Lens C C-04 closure
# ---------------------------------------------------------------------------


def test_soft_advance_preserves_uncommitted_working_tree(tmp_path: Path) -> None:
    """A soft fast-forward MUST NOT scrub uncommitted changes."""
    repo = tmp_path / "repo"
    initial, after = _init(repo)
    # Stage an uncommitted mutation on top of `initial`.
    (repo / "wip.txt").write_text("in-progress", encoding="utf-8")
    _run("git", "add", "wip.txt", cwd=repo)
    # And an unstaged dirty edit.
    (repo / "a.txt").write_text("dirty", encoding="utf-8")

    _fast_forward_head(repo, after, branch="main", soft=True)

    # HEAD advanced.
    assert _run("git", "rev-parse", "HEAD", cwd=repo) == after
    # But wip.txt is still there (soft did not wipe the tree).
    assert (repo / "wip.txt").is_file()
    assert (repo / "wip.txt").read_text() == "in-progress"
    # And the dirty edit to a.txt survived too.
    assert (repo / "a.txt").read_text() == "dirty"


def test_hard_advance_scrubs_working_tree(tmp_path: Path) -> None:
    """Legacy ``soft=False`` path must still scrub the tree."""
    repo = tmp_path / "repo"
    initial, after = _init(repo)
    (repo / "wip.txt").write_text("in-progress", encoding="utf-8")
    _run("git", "add", "wip.txt", cwd=repo)
    (repo / "a.txt").write_text("dirty", encoding="utf-8")

    _fast_forward_head(repo, after, branch="main", soft=False)

    assert _run("git", "rev-parse", "HEAD", cwd=repo) == after
    # Hard reset scrubs uncommitted staged files not tracked in `after`.
    assert not (repo / "wip.txt").is_file()
    # And dirty edit is reverted.
    assert (repo / "a.txt").read_text() == "second"


def test_non_ancestor_target_is_refused_silently(tmp_path: Path) -> None:
    """A divergent-branch target must leave HEAD untouched."""
    repo = tmp_path / "repo"
    initial, _after = _init(repo)
    # Create a divergent commit on a side branch.
    _run("git", "checkout", "-q", "-b", "side", cwd=repo)
    (repo / "b.txt").write_text("side", encoding="utf-8")
    _run("git", "add", "-A", cwd=repo)
    _run("git", "commit", "-q", "-m", "side", cwd=repo)
    side_sha = _run("git", "rev-parse", "HEAD", cwd=repo)
    # Return to main and diverge.
    _run("git", "checkout", "-q", "main", cwd=repo)
    (repo / "c.txt").write_text("main-only", encoding="utf-8")
    _run("git", "add", "-A", cwd=repo)
    _run("git", "commit", "-q", "-m", "main-only", cwd=repo)
    main_after = _run("git", "rev-parse", "HEAD", cwd=repo)

    # side_sha is NOT an ancestor of HEAD (main_after).
    _fast_forward_head(repo, side_sha, branch="main", soft=True)

    # HEAD unchanged.
    assert _run("git", "rev-parse", "HEAD", cwd=repo) == main_after


def test_default_soft_kwarg_is_false_for_backward_compat(tmp_path: Path) -> None:
    """Callers who do not pass ``soft`` get the legacy hard path.

    Backward-compat with any external caller: only the production
    loop path routes through ``soft=True`` (see loop.py _finalize).
    """
    repo = tmp_path / "repo"
    initial, after = _init(repo)
    (repo / "wip.txt").write_text("in-progress", encoding="utf-8")
    _run("git", "add", "-A", cwd=repo)

    _fast_forward_head(repo, after)  # no soft= kwarg

    assert _run("git", "rev-parse", "HEAD", cwd=repo) == after
    # Default = hard, wip.txt was staged but not in `after`, so gone.
    assert not (repo / "wip.txt").is_file()


# RACT 0.5.1
