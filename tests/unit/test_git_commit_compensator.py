"""Git commit compensator on loop-disposal -- unit tests (v0.5.1 module_05).

SUBSTRATE §7 hardening: a commit that lands inside a substrate loop
installs a compensator; unsuccessful loop disposal drains the stack
and reverts each commit; successful disposal (T1) discards the stack
without touching git.

Tests build throwaway git repos under ``tmp_path`` so the compensator
has a real git history to reset. Push boundary is exercised via a
second repo added as a remote.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ract.executor.commit_compensator import (
    CompensatorPushedError,
    CompensatorStack,
    build_compensator,
    check_pushed,
)


# ---------------------------------------------------------------------------
# Helpers -- throwaway repo
# ---------------------------------------------------------------------------


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
# Core: T1 discards, T2 drains
# ---------------------------------------------------------------------------


def test_success_disposal_discards_stack_without_touching_git(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    sha_before = _init_repo(repo)
    sha_after = _add_commit(repo, "one.py", "one")
    stack = CompensatorStack()
    stack.install(
        build_compensator(
            repo,
            branch="main",
            sha_before=sha_before,
            sha_after=sha_after,
        )
    )
    stack.discard(reason="T1_SUCCESS")
    assert _run("git", "rev-parse", "HEAD", cwd=repo) == sha_after
    assert stack.pending() == ()


def test_unsuccessful_disposal_drains_and_reverts_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha_before = _init_repo(repo)
    sha_after = _add_commit(repo, "one.py", "one")
    stack = CompensatorStack()
    stack.install(
        build_compensator(
            repo,
            branch="main",
            sha_before=sha_before,
            sha_after=sha_after,
            mode="soft",
        )
    )
    outcomes = stack.drain(reason="T2_regression")
    assert len(outcomes) == 1
    _comp, status = outcomes[0]
    assert status == "applied"
    assert _run("git", "rev-parse", "HEAD", cwd=repo) == sha_before


def test_lifo_drain_undoes_multiple_commits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha0 = _init_repo(repo)
    sha1 = _add_commit(repo, "one.py", "one")
    sha2 = _add_commit(repo, "two.py", "two")
    stack = CompensatorStack()
    stack.install(
        build_compensator(
            repo, branch="main", sha_before=sha0, sha_after=sha1, mode="hard"
        )
    )
    stack.install(
        build_compensator(
            repo, branch="main", sha_before=sha1, sha_after=sha2, mode="hard"
        )
    )
    outcomes = stack.drain(reason="T2")
    statuses = [status for _, status in outcomes]
    assert statuses == ["applied", "applied"], (
        f"expected LIFO drain to fully unwind; got {statuses}"
    )
    assert _run("git", "rev-parse", "HEAD", cwd=repo) == sha0


# ---------------------------------------------------------------------------
# Push boundary
# ---------------------------------------------------------------------------


def test_pushed_commit_refuses_compensator(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()
    _run("git", "init", "-q", "--bare", cwd=origin)

    repo = tmp_path / "repo"
    sha_before = _init_repo(repo)
    sha_after = _add_commit(repo, "pushed.py", "pushed")
    _run("git", "remote", "add", "origin", str(origin), cwd=repo)
    _run("git", "push", "-q", "origin", "main", cwd=repo)

    assert check_pushed(repo, sha_after) is True
    comp = build_compensator(
        repo,
        branch="main",
        sha_before=sha_before,
        sha_after=sha_after,
    )
    assert comp.pushed is True
    with pytest.raises(CompensatorPushedError):
        comp.apply()


def test_unpushed_commit_admits_compensator(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha_before = _init_repo(repo)
    sha_after = _add_commit(repo, "local.py", "local")
    assert check_pushed(repo, sha_after) is False
    comp = build_compensator(
        repo, branch="main", sha_before=sha_before, sha_after=sha_after
    )
    assert comp.pushed is False
    assert comp.apply() is True


# ---------------------------------------------------------------------------
# HEAD-moved refusal
# ---------------------------------------------------------------------------


def test_soft_refuse_when_head_moved_past_sha_after(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha_before = _init_repo(repo)
    sha_after = _add_commit(repo, "one.py", "one")
    comp = build_compensator(
        repo, branch="main", sha_before=sha_before, sha_after=sha_after
    )
    # Simulate a later, non-loop-owned commit that moves HEAD past.
    _add_commit(repo, "two.py", "two")
    assert comp.apply() is False
    # The downstream commit must still be reachable.
    log = _run("git", "log", "--format=%s", cwd=repo)
    assert "add two.py" in log


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_double_apply_raises(tmp_path: Path) -> None:
    from ract.executor.commit_compensator import CompensatorAlreadyApplied

    repo = tmp_path / "repo"
    sha_before = _init_repo(repo)
    sha_after = _add_commit(repo, "one.py", "one")
    comp = build_compensator(
        repo, branch="main", sha_before=sha_before, sha_after=sha_after
    )
    assert comp.apply() is True
    with pytest.raises(CompensatorAlreadyApplied):
        comp.apply()


# ---------------------------------------------------------------------------
# Events surface
# ---------------------------------------------------------------------------


def test_install_and_drain_emit_events(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha_before = _init_repo(repo)
    sha_after = _add_commit(repo, "one.py", "one")
    events: list = []
    stack = CompensatorStack(event_sink=lambda k, p: events.append((k, p)))
    stack.install(
        build_compensator(
            repo, branch="main", sha_before=sha_before, sha_after=sha_after
        )
    )
    stack.drain(reason="T2")
    kinds = [k for k, _ in events]
    assert kinds == ["compensator.installed", "compensator.applied"]


def test_discard_emits_event(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha_before = _init_repo(repo)
    sha_after = _add_commit(repo, "one.py", "one")
    events: list = []
    stack = CompensatorStack(event_sink=lambda k, p: events.append((k, p)))
    stack.install(
        build_compensator(
            repo, branch="main", sha_before=sha_before, sha_after=sha_after
        )
    )
    stack.discard(reason="T1_SUCCESS")
    kinds = [k for k, _ in events]
    assert kinds == ["compensator.installed", "compensator.discarded"]


# ---------------------------------------------------------------------------
# Mode validation
# ---------------------------------------------------------------------------


def test_build_compensator_rejects_invalid_mode(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo(repo)
    with pytest.raises(ValueError, match="mode must be"):
        build_compensator(
            repo, branch="main", sha_before=sha, sha_after=sha, mode="fuzz"
        )


# RACT 0.5.1
