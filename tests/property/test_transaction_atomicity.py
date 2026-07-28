"""Property tests for SUBSTRATE §3: worktree-per-step transaction atomicity.

Every test builds a throwaway git repo under ``tmp_path`` (so ``git
worktree add`` has an object store to share) and drives the substrate
loop end-to-end. No container backend is exercised — the ``runtime_image``
field stays ``None`` on every step spec so the container shim is bypassed.
Container behavior is covered separately in ``test_container_backends.py``.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from ract.core.loop import WorkspaceSnapshot
from ract.core.predicate import (
    AcceptancePredicate,
    ArtifactInvocation,
    new_predicate_id,
)
from ract.core.transaction import (
    ResourceBudget,
    TransactionOutcome,
    new_step_id,
)
from ract.executor.loop import SubstrateLoop, SubstrateStepSpec
from ract.executor.worktree import WorktreeManager, resolve_head_sha
from ract.handshake_registry import HandshakeRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_repo(repo: Path) -> str:
    """Initialize ``repo`` as a git repo and return the initial commit sha."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "test"],
        ["git", "config", "commit.gpgsign", "false"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True, env=env)
    (repo / "seed.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"], cwd=repo, check=True, capture_output=True, env=env
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"],
        cwd=repo, check=True, capture_output=True, env=env,
    )
    return resolve_head_sha(repo)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[Path]:
    """A throwaway git repo with one seed commit."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    yield root


def _always_ok_predicate() -> AcceptancePredicate:
    # An artifact predicate that reads pre-computed metadata is the cheapest
    # ``ok=True`` you can spell without touching disk.
    return AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(path="__always_ok__", must_have_rootknot=False),
        required=True,
    )


def _always_fail_predicate() -> AcceptancePredicate:
    return AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(
            path="__never_present_anywhere__", must_have_rootknot=False,
        ),
        required=True,
    )


def _ok_snapshot(files: dict[str, str] | None = None) -> WorkspaceSnapshot:
    # ``evaluate_artifact`` checks the path is present in ``ws.files``; the
    # sentinel entry is what our ``_always_ok_predicate`` looks for.
    base = {"__always_ok__": ""}
    if files:
        base.update(files)
    return WorkspaceSnapshot(files=base)


def _fail_snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(files={}, metadata={})


def _writer_runner(rel_path: str, content: str, snapshot: WorkspaceSnapshot):
    """Return a step_runner that writes ``rel_path`` in the worktree and yields
    the given snapshot for post-condition evaluation."""

    def _runner(wt, _container):  # noqa: ANN001
        (wt.path / rel_path).write_text(content, encoding="utf-8")
        return snapshot

    return _runner


# ---------------------------------------------------------------------------
# 1. No partial commit on failure
# ---------------------------------------------------------------------------


def test_no_partial_commit_on_failure(repo: Path) -> None:
    """A step whose post-conditions fail leaves parent_snapshot unchanged and
    no orphan rootact/step/* branch."""
    parent = resolve_head_sha(repo)
    loop = SubstrateLoop(repo_root=repo, parent_snapshot=parent)
    spec = SubstrateStepSpec(
        step_id=new_step_id(),
        predicates=(_always_fail_predicate(),),
        budget=ResourceBudget(wall_seconds=5),
    )

    record = loop.run_step(
        spec, _writer_runner("scratch.txt", "x", _fail_snapshot())
    )

    assert record.outcome is TransactionOutcome.ROLLED_BACK
    assert loop.parent_snapshot == parent
    # No dangling branch.
    manager = WorktreeManager(repo)
    assert spec.step_id.hex() not in " ".join(manager.list_active())


# ---------------------------------------------------------------------------
# 2. Worktree names are discoverable
# ---------------------------------------------------------------------------


def test_worktree_names_are_discoverable(repo: Path) -> None:
    """After N steps, ``git branch --list rootact/step/*`` returns exactly
    the expected N branches (open + committed together)."""
    parent = resolve_head_sha(repo)
    loop = SubstrateLoop(repo_root=repo, parent_snapshot=parent)
    step_ids: list[bytes] = []
    for i in range(3):
        sid = new_step_id()
        step_ids.append(sid)
        spec = SubstrateStepSpec(
            step_id=sid,
            predicates=(_always_ok_predicate(),),
            commit_message=f"step {i}",
        )
        record = loop.run_step(
            spec, _writer_runner(f"step_{i}.txt", "content", _ok_snapshot()),
        )
        assert record.outcome is TransactionOutcome.COMMITTED

    manager = WorktreeManager(repo)
    branches = manager.list_active()
    expected = {f"rootact/step/{sid.hex()}" for sid in step_ids}
    assert set(branches) == expected


# ---------------------------------------------------------------------------
# 3. Handshake blocks dependent commit
# ---------------------------------------------------------------------------


def test_handshake_blocks_dependent_commit(repo: Path, tmp_path: Path) -> None:
    """A step with ``handshake_ids`` referencing a pending handshake returns
    ``BLOCKED_ON_HANDSHAKE`` and does not advance the parent snapshot; a step
    with no such gate proceeds."""
    parent = resolve_head_sha(repo)
    handshakes = HandshakeRegistry(repo)
    handshakes.add(
        "gate-001",
        description="High-risk publish",
        acceptance="operator approval",
    )
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=parent,
        handshake_registry=handshakes,
    )

    blocked_spec = SubstrateStepSpec(
        step_id=new_step_id(),
        predicates=(_always_ok_predicate(),),
        handshake_ids=("gate-001",),
    )
    record = loop.run_step(
        blocked_spec, _writer_runner("blocked.txt", "b", _ok_snapshot())
    )
    assert record.outcome is TransactionOutcome.BLOCKED_ON_HANDSHAKE
    assert loop.parent_snapshot == parent

    # A step with no handshake gate proceeds off the same parent.
    open_spec = SubstrateStepSpec(
        step_id=new_step_id(),
        predicates=(_always_ok_predicate(),),
    )
    record2 = loop.run_step(
        open_spec, _writer_runner("open.txt", "o", _ok_snapshot())
    )
    assert record2.outcome is TransactionOutcome.COMMITTED
    assert loop.parent_snapshot != parent

    # Once the operator resolves the handshake, a fresh attempt at the same
    # gate commits.
    handshakes.update_status("gate-001", "approved")
    followup_spec = SubstrateStepSpec(
        step_id=new_step_id(),
        predicates=(_always_ok_predicate(),),
        handshake_ids=("gate-001",),
    )
    record3 = loop.run_step(
        followup_spec, _writer_runner("followup.txt", "f", _ok_snapshot())
    )
    assert record3.outcome is TransactionOutcome.COMMITTED


# ---------------------------------------------------------------------------
# 4. Rollback is ten-second verifiable (Hypothesis series)
# ---------------------------------------------------------------------------


@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    fail_pattern=st.lists(st.booleans(), min_size=1, max_size=4),
)
def test_rollback_is_ten_second_verifiable(
    repo: Path, fail_pattern: list[bool]
) -> None:
    """For an arbitrary series of fail-then-rollback vs commit steps, after
    each rollback ``git worktree list`` no longer names the removed
    worktree and the branch has been dropped."""
    parent = resolve_head_sha(repo)
    loop = SubstrateLoop(repo_root=repo, parent_snapshot=parent)
    manager = WorktreeManager(repo)

    for i, should_fail in enumerate(fail_pattern):
        sid = new_step_id()
        pred = _always_fail_predicate() if should_fail else _always_ok_predicate()
        snap = _fail_snapshot() if should_fail else _ok_snapshot()
        spec = SubstrateStepSpec(
            step_id=sid,
            predicates=(pred,),
            commit_message=f"pattern step {i}",
        )
        record = loop.run_step(spec, _writer_runner(f"p_{i}.txt", "x", snap))
        expected_branch = f"rootact/step/{sid.hex()}"
        if should_fail:
            assert record.outcome is TransactionOutcome.ROLLED_BACK
            # Rolled-back steps must not name the worktree in the porcelain
            # listing and must not leave a step branch.
            entries = manager.worktree_list()
            worktrees = {rec.get("worktree", "") for rec in entries}
            assert not any(sid.hex() in wt for wt in worktrees)
            assert expected_branch not in manager.list_active()
        else:
            assert record.outcome is TransactionOutcome.COMMITTED
            assert expected_branch in manager.list_active()
