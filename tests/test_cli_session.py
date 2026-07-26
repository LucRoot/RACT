"""Smoke tests for the v0.4 ``ract session ls`` and ``ract session diff``
CLI verbs (SUBSTRATE §3, module_02 CLI leaf).

The verbs are lightweight wrappers over the substrate worktree manager;
these tests build a throwaway git repo, drive one committed step
transaction, and assert the CLI enumerates it and prints its patch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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
        ["git", "add", "-A"], cwd=root, check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"], cwd=root, check=True,
        capture_output=True, env=env,
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


@pytest.fixture
def committed_repo(tmp_path: Path) -> tuple[Path, bytes]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    parent = resolve_head_sha(repo)
    loop = SubstrateLoop(repo_root=repo, parent_snapshot=parent)
    sid = new_step_id()
    spec = SubstrateStepSpec(
        step_id=sid,
        predicates=(_ok_pred(),),
        commit_message="cli-smoke step",
    )

    def runner(wt, _c):  # noqa: ANN001
        (wt.path / "hello.txt").write_text("cli-smoke\n", encoding="utf-8")
        return _ok_snapshot()

    record = loop.run_step(spec, runner)
    assert record.outcome.name == "COMMITTED"
    return repo, sid


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "session", *args],
        capture_output=True, text=True, check=False, cwd=cwd,
    )


def test_session_ls_lists_committed_step(committed_repo: tuple[Path, bytes]) -> None:
    repo, sid = committed_repo
    result = _run_cli("ls", "--repo", str(repo), "--json", cwd=repo)
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    step_ids = {row["step_id"] for row in rows}
    assert sid.hex() in step_ids


def test_session_diff_prints_patch(committed_repo: tuple[Path, bytes]) -> None:
    repo, sid = committed_repo
    # Use the initial commit as the parent — the merge-base fallback also
    # works, but pinning ``--parent`` keeps the assertion deterministic.
    parent = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD~1"],
        capture_output=True, text=True, check=False,
    ).stdout.strip() or subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    result = _run_cli(
        "diff", sid.hex(), "--repo", str(repo), "--parent", parent,
        "--json", cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["step_id"] == sid.hex()
    assert "hello.txt" in payload["patch"]


def test_session_ls_help_registers() -> None:
    """The DoD leaf: `ract session ls --help` is discoverable."""
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "session", "ls", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "worktree" in result.stdout.lower()


def test_session_diff_help_registers() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "session", "diff", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "step_id" in result.stdout.lower()
