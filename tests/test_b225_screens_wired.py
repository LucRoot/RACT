"""B-225: the git screens reach the terminal in the real tier-2 git questions.

``ui/git_screens.py`` was in the tree and imported by nothing; the operator saw
the older question. The commit, branch and worktree questions now print the
slice (f) screens, with the exact command quoted on them (G-239 D8).
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from ract import approval_callback
from ract.tools.git_tools import BranchArgs, CommitArgs, WorktreeArgs, _Staged


def _ask(name: str, args: object, width: int, monkeypatch, capsys) -> str:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(approval_callback, "_terminal_width", lambda: width + 3)
    monkeypatch.setattr(approval_callback, "read_line", lambda _p: "n")
    assert approval_callback.console_tier_2_choice(name, args) == "deny"
    return capsys.readouterr().out


@pytest.mark.parametrize("width", [80, 60])
def test_the_commit_question_is_the_commit_screen(width: int, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    args = CommitArgs(message="fix the adder")
    args._staged = _Staged(files=(("M", "src/calc.py", "1", "1"),), digest="d", scanned=1)
    out = _ask("git_commit", args, width, monkeypatch, capsys)
    assert "commit (tier 2)" in out
    assert "command: git commit -m 'fix the adder'" in " ".join(out.split())
    assert "message (the model wrote this text): fix the adder" in " ".join(out.split())
    assert "src/calc.py" in out and "[y]es, commit" in out
    assert all(cell_len(line) <= width + 3 for line in out.splitlines()), out


@pytest.mark.parametrize("width", [80, 60])
def test_the_branch_and_worktree_questions_are_their_screens(
    width: int, monkeypatch, capsys  # type: ignore[no-untyped-def]
) -> None:
    out = _ask("git_branch", BranchArgs(name="topic"), width, monkeypatch, capsys)
    assert "branch (tier 2)" in out and "create branch topic" in out
    out = _ask("git_worktree", WorktreeArgs(action="add", name="w1"), width, monkeypatch, capsys)
    assert "worktree (tier 2)" in out and ".ract/worktrees/w1" in out


@pytest.mark.parametrize("width", [80, 30])
def test_the_command_on_the_screen_keeps_every_space(width: int, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """B-184 on the B-225 screen: a run of spaces in the quoted message stays."""
    args = CommitArgs(message="fix  the   adder")
    args._staged = _Staged(files=(("M", "src/calc.py", "1", "1"),), digest="d", scanned=1)
    out = _ask("git_commit", args, width, monkeypatch, capsys)
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("command: "))
    folded = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.startswith("    "):
            break
        folded.append(line[4:])
    assert "".join(folded) == "command: git commit -m 'fix  the   adder'", folded
    assert all(cell_len(line) <= width + 3 for line in lines), out


@pytest.mark.parametrize("columns", ["80", "60"])
def test_doctor_prints_the_sandbox_posture_screen(columns: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # B-225: the slice (e) screen is the doctor's sandbox section.
    import os
    import subprocess
    import sys

    from tests.ux import run_baseline as rb

    ws = tmp_path / "ws"
    ws.mkdir()
    rb._configure(ws, "http://127.0.0.1:9/v1", "fake-coder")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env.update(NO_COLOR="1", COLUMNS=columns, RACT_NO_NETWORK="1")
    done = subprocess.run(
        [sys.executable, "-m", "ract.cli", "doctor", "--config", "ract.yaml"],
        cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=env,
    )
    lines = done.stdout.splitlines()
    start = [line.strip() for line in lines].index("sandbox")
    section = lines[start : start + 3]
    assert "best effort, not enforced on this machine" in " ".join(" ".join(section).split())
    assert all(len(line) <= int(columns) for line in section), section
