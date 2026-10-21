"""S-011: a run never commits onto the operator's branch.

Before this fix the substrate path committed each step and fast-forwarded the
checked-out branch with ``git reset --soft``: the user got a ``rootact step``
commit they did not ask for, the working file was left unchanged, and the
index held a staged change that reverted the commit (UX baseline UX-01 and
UX-06). A read-only question and a denied approval also left a commit.

Each case runs the real CLI against the scripted fake model server in a
throwaway git repository and checks HEAD, the branch, the index and the file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.ux import run_baseline as rb


def _git(ws: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True
    ).stdout.strip()


def _run(ws: Path, intent: str, *extra: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", *extra, intent],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def _repo(tmp_path: Path, server: Any, files: dict[str, str]) -> Path:
    ws = rb._workspace(tmp_path, "ws", git=True, files=files)
    rb._configure(ws, server.base_url, "fake-coder")
    # ract.yaml and prompts/ are the operator's own files; commit them so the
    # tree is clean, as the substrate path requires.
    _git(ws, "add", "-A")
    _git(
        ws,
        "-c",
        "user.name=demo",
        "-c",
        "user.email=demo@example.invalid",
        "commit",
        "-q",
        "-m",
        "config",
    )
    return ws


def test_fix_lands_as_unstaged_change_and_branch_does_not_move(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server, rb.CALC_FILES)
    head_before = _git(ws, "rev-parse", "HEAD")
    branch_before = _git(ws, "branch", "--show-current")

    result = _run(ws, "tests/test_calc.py::test_add fails, fix it")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(ws, "rev-parse", "HEAD") == head_before
    assert _git(ws, "branch", "--show-current") == branch_before
    assert _git(ws, "diff", "--cached", "--name-only") == ""
    assert _git(ws, "diff", "--name-only") == "src/calc.py"
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")
    # The step's commit is kept on its own branch for the record.
    assert _git(ws, "branch", "--list", "rootact/step/*")


def test_read_only_question_does_not_commit(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j3_today")
    ws = _repo(tmp_path, server, rb.APP_FILES)
    head_before = _git(ws, "rev-parse", "HEAD")

    _run(ws, "where is the config loader and who calls it?")

    assert _git(ws, "rev-parse", "HEAD") == head_before
    assert _git(ws, "diff", "--cached", "--name-only") == ""


def test_denied_approval_does_not_commit(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j3_today")
    ws = _repo(tmp_path, server, rb.APP_FILES)
    head_before = _git(ws, "rev-parse", "HEAD")

    # --auto asks for each step on stdin; stdin is closed, so it is denied.
    _run(ws, "where is the config loader and who calls it?", "--auto")

    assert _git(ws, "rev-parse", "HEAD") == head_before
    assert _git(ws, "status", "--porcelain", "--untracked-files=no") == ""


def test_ract_state_is_never_copied_into_the_working_tree(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server, rb.CALC_FILES)

    _run(ws, "tests/test_calc.py::test_add fails, fix it")

    tracked_ract = _git(ws, "ls-files", ".ract")
    assert tracked_ract == ""
    staged = _git(ws, "diff", "--cached", "--name-only")
    assert ".ract" not in staged


@pytest.mark.parametrize("conflicting", [True])
def test_file_changed_during_the_step_is_left_alone(
    tmp_path: Path, conflicting: bool
) -> None:
    from ract.executor.worktree import apply_commit_to_working_tree

    ws = rb._workspace(
        tmp_path, "ws", git=True, files={"a.txt": "one\n", "b.txt": "x\n"}
    )
    before = _git(ws, "rev-parse", "HEAD")
    _git(ws, "checkout", "-q", "-b", "step")
    (ws / "a.txt").write_text("two\n", encoding="utf-8")
    (ws / "b.txt").write_text("y\n", encoding="utf-8")
    _git(
        ws,
        "-c",
        "user.name=d",
        "-c",
        "user.email=d@example.invalid",
        "commit",
        "-q",
        "-am",
        "step",
    )
    after = _git(ws, "rev-parse", "HEAD")
    _git(ws, "checkout", "-q", "-")
    if conflicting:
        (ws / "a.txt").write_text("operator edit\n", encoding="utf-8")

    applied, skipped, patch_path = apply_commit_to_working_tree(ws, before, after)

    assert applied == ["b.txt"]
    assert skipped == ["a.txt"]
    assert (ws / "a.txt").read_text(encoding="utf-8") == "operator edit\n"
    assert (ws / "b.txt").read_text(encoding="utf-8").strip() == "y"
    assert patch_path.startswith(".ract/pending/")
    assert "two" in (ws / patch_path).read_text(encoding="utf-8")
