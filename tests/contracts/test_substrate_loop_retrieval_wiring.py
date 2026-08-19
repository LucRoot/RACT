"""module_09: SubstrateLoop reads metadata['retrieval_bundle'] and emits.

Contract: when a caller populates ``SubstrateStepSpec.metadata['retrieval_
bundle']`` with any object exposing ``total_tokens`` /
``budget_used_pct`` / ``call_id``, ``SubstrateLoop.run_step`` emits a
``retrieval.satisfied`` event with those numbers copied into the
payload. A spec without the key produces no such event. The
metadata field defaults to ``{}`` so v0.4.x callers see no behavior
change.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ract.core.loop import WorkspaceSnapshot
from ract.core.predicate import (
    AcceptancePredicate,
    ArtifactInvocation,
    new_predicate_id,
)
from ract.core.transaction import new_step_id
from ract.executor.loop import SubstrateLoop, SubstrateStepSpec
from ract.executor.worktree import resolve_head_sha


def _init_repo(root: Path) -> None:
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
        ["git", "add", "-A"], cwd=root, check=True, capture_output=True, env=env
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"],
        cwd=root,
        check=True,
        capture_output=True,
        env=env,
    )


def _ok_pred() -> AcceptancePredicate:
    return AcceptancePredicate(
        id=new_predicate_id(),
        kind="artifact",
        invocation=ArtifactInvocation(path="__always_ok__", must_have_rootknot=False),
        required=True,
    )


def _ok_snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(files={"__always_ok__": ""})


@dataclass
class _StubBundle:
    """Minimal stand-in for a RetrievalBundle (the loop reads three fields)."""

    total_tokens: int = 512
    budget_used_pct: float = 42.5
    call_id: str = "stub-call-id"


def test_metadata_bundle_emits_retrieval_satisfied(tmp_path: Path) -> None:
    """A step with metadata['retrieval_bundle'] set emits retrieval.satisfied."""
    from ract.trace import sink as _sink

    events: list[tuple] = []

    def _fake_emit(kind, payload, step_id=None, parent_id=None):  # noqa: ANN001
        events.append((kind, payload, step_id))

    original = _sink.emit
    _sink.emit = _fake_emit  # type: ignore[assignment]
    try:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        parent = resolve_head_sha(repo)

        loop = SubstrateLoop(repo_root=repo, parent_snapshot=parent)
        bundle = _StubBundle(total_tokens=777, budget_used_pct=88.25, call_id="c-1")
        spec = SubstrateStepSpec(
            step_id=new_step_id(),
            predicates=(_ok_pred(),),
            commit_message="module_09 wiring",
            metadata={"retrieval_bundle": bundle},
        )

        def runner(wt, _c):  # noqa: ANN001
            (wt.path / "hello.txt").write_text("hi\n", encoding="utf-8")
            return _ok_snapshot()

        record = loop.run_step(spec, runner)
        assert record.outcome.name == "COMMITTED", record.reason
    finally:
        _sink.emit = original  # type: ignore[assignment]

    # The retrieval.satisfied event was emitted with the bundle numbers.
    satisfied = [e for e in events if e[0] == "retrieval.satisfied"]
    assert len(satisfied) == 1, [e[0] for e in events]
    payload = satisfied[0][1]
    assert payload["total_tokens"] == 777
    assert payload["budget_used_pct"] == 88.25
    assert payload["call_id"] == "c-1"


def test_metadata_absent_emits_no_retrieval_event(tmp_path: Path) -> None:
    """A step without metadata['retrieval_bundle'] emits no retrieval event."""
    from ract.trace import sink as _sink

    events: list[tuple] = []

    def _fake_emit(kind, payload, step_id=None, parent_id=None):  # noqa: ANN001
        events.append((kind, payload, step_id))

    original = _sink.emit
    _sink.emit = _fake_emit  # type: ignore[assignment]
    try:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        parent = resolve_head_sha(repo)

        loop = SubstrateLoop(repo_root=repo, parent_snapshot=parent)
        spec = SubstrateStepSpec(
            step_id=new_step_id(),
            predicates=(_ok_pred(),),
            commit_message="no metadata",
        )

        def runner(wt, _c):  # noqa: ANN001
            (wt.path / "hello.txt").write_text("hi\n", encoding="utf-8")
            return _ok_snapshot()

        record = loop.run_step(spec, runner)
        assert record.outcome.name == "COMMITTED"
    finally:
        _sink.emit = original  # type: ignore[assignment]

    assert not [e for e in events if e[0] == "retrieval.satisfied"]


def test_metadata_default_empty_dict_is_backward_compatible() -> None:
    """SubstrateStepSpec.metadata defaults to an empty dict.

    v0.4.x callers that construct a spec without the field see today's
    behavior; the loop never inspects a missing key.
    """
    spec = SubstrateStepSpec()
    assert spec.metadata == {}


# RACT 0.5.0
