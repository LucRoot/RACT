"""SubstrateLoop compensator wiring -- SP Q5(b) + Q5(c) amendments.

Locks the invariants surfaced by the module_05 Second Pass
(OpenRouter DEFECT verdict):

- Q5(b): fast-forward failure MUST NOT advance
  ``self.parent_snapshot`` (loop state stays in sync with git state).
- Q5(c): ``dispose(success=False)`` MUST resync
  ``self.parent_snapshot`` to actual git HEAD after the compensator
  stack drains.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


from ract.executor.commit_compensator import build_compensator
from ract.executor.loop import SubstrateLoop
from ract.executor.worktree import WorktreeManager, resolve_head_sha


def _run(*argv: str, cwd: Path) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_TERMINAL_PROMPT": "0",
    }
    result = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, check=True, env=env
    )
    return result.stdout.strip()


def _init_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    _run("git", "init", "-q", "-b", "main", cwd=root)
    (root / "seed.txt").write_text("seed", encoding="utf-8")
    _run("git", "add", "-A", cwd=root)
    _run("git", "commit", "-q", "-m", "seed", cwd=root)
    return _run("git", "rev-parse", "HEAD", cwd=root)


def _add_commit(root: Path, name: str, body: str) -> str:
    (root / name).write_text(body, encoding="utf-8")
    _run("git", "add", "-A", cwd=root)
    _run("git", "commit", "-q", "-m", f"add {name}", cwd=root)
    return _run("git", "rev-parse", "HEAD", cwd=root)


# ---------------------------------------------------------------------------
# Q5(c) -- dispose resyncs parent_snapshot after drain
# ---------------------------------------------------------------------------


def test_sp_q5c_dispose_resyncs_parent_snapshot_after_drain(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )
    # Install a compensator directly (bypass _finalize for isolation).
    after = _add_commit(repo, "one.py", "one")
    loop.parent_snapshot = after
    loop.compensator_stack.install(
        build_compensator(repo, branch="main", sha_before=initial, sha_after=after)
    )
    # Dispose unsuccessfully -- compensator drains + resync.
    loop.dispose(success=False, reason="T2_test")
    # Git HEAD went back to initial.
    assert resolve_head_sha(repo) == initial
    # Loop's parent_snapshot resynced to actual HEAD.
    assert loop.parent_snapshot == initial


def test_sp_q5c_dispose_success_does_not_touch_parent_snapshot(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=initial,
        worktree_manager=WorktreeManager(repo),
    )
    after = _add_commit(repo, "one.py", "one")
    loop.parent_snapshot = after
    loop.compensator_stack.install(
        build_compensator(repo, branch="main", sha_before=initial, sha_after=after)
    )
    loop.dispose(success=True, reason="T1_SUCCESS")
    # HEAD still at 'after' (T1 discards; does NOT touch git).
    assert resolve_head_sha(repo) == after
    # parent_snapshot untouched by dispose.
    assert loop.parent_snapshot == after


# ---------------------------------------------------------------------------
# Q5(b) -- dispose is idempotent-safe when nothing to drain
# ---------------------------------------------------------------------------


def test_sp_q5c_empty_stack_drain_still_resyncs(tmp_path: Path) -> None:
    """Even when the stack is empty, dispose(success=False) resyncs."""
    repo = tmp_path / "repo"
    initial = _init_repo(repo)
    # Simulate a stale loop.parent_snapshot value that never matched git.
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot="deadbeef" * 5,
        worktree_manager=WorktreeManager(repo),
    )
    loop.dispose(success=False, reason="T2_empty_stack")
    assert loop.parent_snapshot == initial


# RACT 0.5.1
