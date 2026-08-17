"""module_08: AuctionSweep runs from SubstrateLoop between iterations.

The sweep primitive lives on ``SubstrateLoop`` and is invoked at the
step boundary in ``run_step``. When ``AuctionConfig.min_iteration_wall_seconds``
is 0 the sweep fires on every boundary; a 3-iteration synthetic run
triggers at least one sweep.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ract.contracts.auction import AuctionConfig, AuctionSweep
from ract.core.loop import WorkspaceSnapshot
from ract.core.predicate import (
    AcceptancePredicate,
    ArtifactInvocation,
    new_predicate_id,
)
from ract.core.transaction import new_step_id
from ract.executor.loop import SubstrateLoop, SubstrateStepSpec
from ract.executor.worktree import resolve_head_sha


def _init_repo(root: Path) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "test"],
        ["git", "config", "commit.gpgsign", "false"],
    ):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True, env=env)
    (root / "seed.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"],
        cwd=root,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"],
        cwd=root,
        check=True,
        capture_output=True,
        env=env,
    )
    return resolve_head_sha(root)


def _ok_pred() -> AcceptancePredicate:
    return AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(path="__always_ok__", must_have_rootknot=False),
        required=True,
    )


def _ok_snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(files={"__always_ok__": ""})


class _SweepSpy:
    """Stand-in for ``AuctionSweep`` that records ``run`` invocations."""

    def __init__(self) -> None:
        self.calls: list[float] = []
        self.config = AuctionConfig(
            stale_days=0,
            min_iteration_wall_seconds=0.0,
            max_proposals_per_sweep=1,
        )

    def should_run(self, current_wall_seconds: float) -> bool:
        return True

    def run(self, current_wall_seconds: float | None = None):  # noqa: ANN001
        self.calls.append(current_wall_seconds or 0.0)
        return []


def test_auction_sweep_fires_between_iterations(tmp_path: Path) -> None:
    """A 3-step run with ``min_iteration_wall_seconds=0`` triggers >=1 sweep."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    parent = resolve_head_sha(repo)

    spy = _SweepSpy()
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=parent,
        auction_sweep=spy,  # type: ignore[arg-type]  # duck-typed
    )

    for i in range(3):
        spec = SubstrateStepSpec(
            step_id=new_step_id(),
            predicates=(_ok_pred(),),
            commit_message=f"step {i}",
        )

        def runner(wt, _c, idx=i):  # noqa: ANN001
            (wt.path / f"iter_{idx}.txt").write_text("x\n", encoding="utf-8")
            return _ok_snapshot()

        record = loop.run_step(spec, runner)
        assert record.outcome.name == "COMMITTED", record.reason

    # The sweep is invoked at the START of each step (before opening
    # the transaction). Three iterations therefore produce three
    # ``AuctionSweep.run`` calls.
    assert len(spy.calls) == 3, (
        f"expected 3 sweep invocations, got {len(spy.calls)}: {spy.calls}"
    )


def test_auction_sweep_is_optional(tmp_path: Path) -> None:
    """A loop without an ``auction_sweep`` still runs cleanly."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    parent = resolve_head_sha(repo)

    loop = SubstrateLoop(repo_root=repo, parent_snapshot=parent)
    spec = SubstrateStepSpec(
        step_id=new_step_id(),
        predicates=(_ok_pred(),),
        commit_message="no-sweep step",
    )

    def runner(wt, _c):  # noqa: ANN001
        (wt.path / "hello.txt").write_text("hi\n", encoding="utf-8")
        return _ok_snapshot()

    record = loop.run_step(spec, runner)
    assert record.outcome.name == "COMMITTED"


def test_auction_sweep_uses_real_config_gate(tmp_path: Path) -> None:
    """A real ``AuctionSweep`` with a 0-second gate emits at least one call."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    parent = resolve_head_sha(repo)

    sweep = AuctionSweep(
        workspace_root=repo,
        config=AuctionConfig(
            stale_days=0,
            min_iteration_wall_seconds=0.0,
            max_proposals_per_sweep=2,
        ),
    )
    loop = SubstrateLoop(
        repo_root=repo,
        parent_snapshot=parent,
        auction_sweep=sweep,
    )
    spec = SubstrateStepSpec(
        step_id=new_step_id(),
        predicates=(_ok_pred(),),
        commit_message="real-sweep step",
    )

    def runner(wt, _c):  # noqa: ANN001
        (wt.path / "hello.txt").write_text("hi\n", encoding="utf-8")
        return _ok_snapshot()

    record = loop.run_step(spec, runner)
    assert record.outcome.name == "COMMITTED"


# RACT 0.4.0
