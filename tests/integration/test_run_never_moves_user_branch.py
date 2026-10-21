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
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ract.executor.worktree import apply_commit_to_working_tree
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


# ---------------------------------------------------------------- the helper never destroys


def _step_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    return rb._workspace(tmp_path, "ws", git=True, files=files)


def _commit_step(ws: Path, edit: Callable[[Path], None]) -> tuple[str, str]:
    """Make a step commit on a side branch; return (before, after)."""
    before = _git(ws, "rev-parse", "HEAD")
    _git(ws, "checkout", "-q", "-b", "step")
    edit(ws)
    _git(ws, "add", "-A")
    _git(
        ws,
        "-c",
        "user.name=d",
        "-c",
        "user.email=d@example.invalid",
        "commit",
        "-q",
        "-m",
        "step",
    )
    after = _git(ws, "rev-parse", "HEAD")
    _git(ws, "checkout", "-q", "-")
    return before, after


def test_untracked_file_at_an_added_path_is_never_overwritten(tmp_path: Path) -> None:
    ws = _step_repo(tmp_path, {"a.txt": "one\n"})
    before, after = _commit_step(
        ws, lambda w: (w / "output.txt").write_text("model\n", encoding="utf-8")
    )
    (ws / "output.txt").write_text("MY OWN NOTES\n", encoding="utf-8")

    result = apply_commit_to_working_tree(ws, before, after)

    assert result.applied == ()
    assert "already exists" in result.skipped["output.txt"]
    assert (ws / "output.txt").read_text(encoding="utf-8") == "MY OWN NOTES\n"
    assert "model" in (ws / result.patch_path).read_text(encoding="utf-8")


def test_untracked_output_txt_survives_a_real_run(
    tmp_path: Path, fake_model_server: Any
) -> None:
    # The G-013 repro (j3_untracked) through the real CLI.
    server = fake_model_server("baseline_j3_today")
    ws = _repo(tmp_path, server, rb.APP_FILES)
    notes = "MY OWN NOTES, not tracked by git\n"
    (ws / "output.txt").write_text(notes, encoding="utf-8")

    _run(ws, "where is the config loader and who calls it?", "--yolo")

    assert (ws / "output.txt").read_text(encoding="utf-8") == notes
    assert list((ws / ".ract" / "pending").glob("*.patch"))


def _edit_a(w: Path) -> None:
    (w / "a.txt").write_text("operator edit\n", encoding="utf-8")


def _delete_a(w: Path) -> None:
    (w / "a.txt").unlink()


@pytest.mark.parametrize(
    "operator_action, expected_reason",
    [(_edit_a, "you changed this file"), (_delete_a, "you deleted this file")],
    ids=["edited", "deleted"],
)
def test_tracked_file_the_operator_touched_is_left_alone(
    tmp_path: Path, operator_action: Callable[[Path], None], expected_reason: str
) -> None:
    ws = _step_repo(tmp_path, {"a.txt": "one\n", "b.txt": "x\n"})

    def edit(w: Path) -> None:
        (w / "a.txt").write_text("two\n", encoding="utf-8")
        (w / "b.txt").write_text("y\n", encoding="utf-8")

    before, after = _commit_step(ws, edit)
    operator_action(ws)

    result = apply_commit_to_working_tree(ws, before, after)

    assert result.applied == ("b.txt",)
    assert expected_reason in result.skipped["a.txt"]
    assert "two" in (ws / result.patch_path).read_text(encoding="utf-8")


def test_step_deleting_a_file_the_operator_edited_keeps_the_edit(
    tmp_path: Path,
) -> None:
    ws = _step_repo(tmp_path, {"a.txt": "one\n"})
    before, after = _commit_step(ws, _delete_a)
    _edit_a(ws)

    result = apply_commit_to_working_tree(ws, before, after)

    assert result.applied == ()
    assert (ws / "a.txt").read_text(encoding="utf-8") == "operator edit\n"


def test_step_deleting_an_untouched_file_deletes_it(tmp_path: Path) -> None:
    ws = _step_repo(tmp_path, {"a.txt": "one\n", "keep.txt": "k\n"})
    before, after = _commit_step(ws, _delete_a)

    result = apply_commit_to_working_tree(ws, before, after)

    assert result.applied == ("a.txt",)
    assert result.skipped == {}
    assert not (ws / "a.txt").exists()


def test_directory_or_ignored_file_at_an_added_path_is_a_conflict(
    tmp_path: Path,
) -> None:
    ws = _step_repo(tmp_path, {".gitignore": "*.log\n", "a.txt": "one\n"})

    def edit(w: Path) -> None:
        (w / "dirpath").write_text("file from step\n", encoding="utf-8")
        (w / "debug.log").write_text("from step\n", encoding="utf-8")
        _git(w, "add", "-f", "debug.log")

    before, after = _commit_step(ws, edit)
    (ws / "dirpath").mkdir()
    (ws / "dirpath" / "inner.txt").write_text("mine\n", encoding="utf-8")
    (ws / "debug.log").write_text("my ignored log\n", encoding="utf-8")

    result = apply_commit_to_working_tree(ws, before, after)

    assert set(result.skipped) == {"dirpath", "debug.log"}
    assert (ws / "dirpath" / "inner.txt").read_text(encoding="utf-8") == "mine\n"
    assert (ws / "debug.log").read_text(encoding="utf-8") == "my ignored log\n"


def test_unknown_change_type_is_a_conflict(tmp_path: Path) -> None:
    from ract.executor.worktree import _classify_for_apply

    ws = _step_repo(tmp_path, {"a.txt": "one\n"})
    head = _git(ws, "rev-parse", "HEAD")
    assert "not applied automatically" in _classify_for_apply(ws, "T", "a.txt", head)


# ---------------------------------------------------------------- undo paths still work


def test_rollback_restores_a_file_the_run_changed(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server, rb.CALC_FILES)
    original = (ws / "src" / "calc.py").read_text(encoding="utf-8")

    _run(ws, "tests/test_calc.py::test_add fails, fix it", "--session", "s1")
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")

    undo = _run(ws, "rollback", "--rollback", "--session", "s1")
    assert undo.returncode == 0, undo.stdout + undo.stderr
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == original


def test_loop_that_does_not_advance_head_installs_no_compensator(
    tmp_path: Path,
) -> None:
    from ract.core.loop import WorkspaceSnapshot
    from ract.core.transaction import ResourceBudget
    from ract.executor.loop import SubstrateLoop, SubstrateStepSpec
    from ract.executor.worktree import WorktreeManager

    ws = _step_repo(tmp_path, {"a.txt": "one\n"})
    head = _git(ws, "rev-parse", "HEAD")
    loop = SubstrateLoop(
        repo_root=ws,
        parent_snapshot=head,
        worktree_manager=WorktreeManager(ws),
        advance_head=False,
    )

    def runner(wt: Any, _container: Any) -> WorkspaceSnapshot:
        (Path(wt.path) / "a.txt").write_text("two\n", encoding="utf-8")
        return WorkspaceSnapshot(files={}, metadata={})

    spec = SubstrateStepSpec(
        predicates=(), budget=ResourceBudget(wall_seconds=60), commit_message="step"
    )
    record = loop.run_step(spec, runner)

    assert record.outcome.name == "COMMITTED"
    assert tuple(loop.compensator_stack.pending()) == ()
    loop.dispose(success=False, reason="test")
    assert _git(ws, "rev-parse", "HEAD") == head
    assert (ws / "a.txt").read_text(encoding="utf-8") == "one\n"
