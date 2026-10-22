"""S-011b: each run starts from a snapshot of the working tree (audit findings).

AUD-001: a plan whose later step changes a file an earlier step created
failed at that step. AUD-002: after any run that edited a tracked file, the
next run silently fell back to writing in place without isolation. Both came
from starting each run at HEAD and requiring a clean tree. The rest are the
apply details found in the same audit (AUD-004, 009, 010, 011, 012).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from ract.executor.worktree import (
    apply_commit_to_working_tree,
    snapshot_working_tree,
)
from tests.fixtures.fake_model_server import Scenario
from tests.ux import run_baseline as rb


def _git(ws: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit_all(ws: Path) -> None:
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
        "c",
    )


def _ract(ws: Path, intent: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", intent],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def _plan(*steps: tuple[str, str]) -> str:
    return json.dumps(
        {
            "assumption": "a",
            "confidence": 0.9,
            "steps": [
                {"action": a, "provider_hint": "local", "expected_artifact": t}
                for a, t in steps
            ],
        }
    )


def _step_branches(ws: Path) -> list[str]:
    return _git(
        ws, "branch", "--list", "rootact/step/*", "--format=%(refname:short)"
    ).splitlines()


# ---------------------------------------------------------------- AUD-001 and AUD-002


def test_create_then_extend_plan_succeeds(
    tmp_path: Path, fake_model_server: Any
) -> None:
    scenario = Scenario.from_dict(
        {
            "turns": [
                {
                    "reply": {
                        "kind": "text",
                        "content": _plan(
                            ("Create util", "src/util.py"),
                            ("Extend util", "src/util.py"),
                        ),
                    }
                },
                {"reply": {"kind": "text", "content": "def a():\n    return 1\n"}},
                {
                    "reply": {
                        "kind": "text",
                        "content": "def a():\n    return 1\n\n\ndef b():\n    return 2\n",
                    }
                },
            ]
        }
    )
    server = fake_model_server(scenario)
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    _commit_all(ws)

    result = _ract(ws, "create util and extend it")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "def b()" in (ws / "src" / "util.py").read_text(encoding="utf-8")
    assert len(_step_branches(ws)) == 2


def test_second_run_on_a_dirty_tree_stays_isolated(
    tmp_path: Path, fake_model_server: Any
) -> None:
    first = fake_model_server("baseline_j4_today")
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, first.base_url, "fake-coder")
    _commit_all(ws)
    assert _ract(ws, "fix add").returncode == 0
    assert _git(ws, "diff", "--name-only") == "src/calc.py"  # dirty now

    second = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {
                        "reply": {
                            "kind": "text",
                            "content": _plan(("Update readme", "README.md")),
                        }
                    },
                    {
                        "reply": {
                            "kind": "text",
                            "content": "# calc\n\nAdds and subtracts.\n",
                        }
                    },
                ]
            }
        )
    )
    (ws / "ract.yaml").write_text(
        (ws / "ract.yaml")
        .read_text(encoding="utf-8")
        .replace(first.base_url, second.base_url),
        encoding="utf-8",
    )
    result = _ract(ws, "update the readme")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "writes directly into your files" not in result.stdout
    assert len(_step_branches(ws)) == 2
    assert "Adds and subtracts." in (ws / "README.md").read_text(encoding="utf-8")
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")


def test_in_place_path_is_announced(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = rb._workspace(tmp_path, "ws", git=False, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")

    result = _ract(ws, "fix add")

    assert (
        "note: this directory is not a git repository; RACT writes directly into your files"
        in result.stdout
    )


# ---------------------------------------------------------------- the snapshot


def test_snapshot_leaves_operator_git_state_alone_and_skips_secrets(
    tmp_path: Path,
) -> None:
    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    (ws / "a.txt").write_text("edited\n", encoding="utf-8")
    (ws / "new.txt").write_text("untracked\n", encoding="utf-8")
    (ws / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (ws / ".ract").mkdir()
    (ws / ".ract" / "state.json").write_text("{}", encoding="utf-8")
    _git(ws, "add", "new.txt")  # staged, to prove the index is untouched
    status_before = _git(ws, "status", "--porcelain")
    index_before = _git(ws, "ls-files", "--stage")

    snap = snapshot_working_tree(ws)

    assert _git(ws, "status", "--porcelain") == status_before
    assert _git(ws, "ls-files", "--stage") == index_before
    assert _git(ws, "stash", "list") == ""
    files = set(_git(ws, "ls-tree", "-r", "--name-only", snap).splitlines())
    assert {"a.txt", "new.txt"} <= files
    assert ".env" not in files and not any(f.startswith(".ract") for f in files)
    assert _git(ws, "show", f"{snap}:a.txt") == "edited"


# ---------------------------------------------------------------- apply details


def _step(ws: Path, edit) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """Make a step commit from a snapshot base in a separate worktree."""
    before = snapshot_working_tree(ws)
    side = ws.parent / f"side-{before[:8]}"
    _git(ws, "worktree", "add", "-q", "--detach", str(side), before)
    edit(side)
    _git(side, "add", "-A")
    _git(
        side,
        "-c",
        "user.name=d",
        "-c",
        "user.email=d@example.invalid",
        "commit",
        "-q",
        "-m",
        "step",
    )
    after = _git(side, "rev-parse", "HEAD")
    _git(ws, "worktree", "remove", "--force", str(side))
    return before, after


def test_aud004_patch_is_bytes_and_applies_for_binary_files(tmp_path: Path) -> None:
    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    (ws / "blob.bin").write_bytes(b"\x00\x01\x02orig")
    _commit_all(ws)
    before, after = _step(
        ws, lambda w: (w / "blob.bin").write_bytes(b"\x00\x01\x02step")
    )
    (ws / "blob.bin").write_bytes(b"\x00\x01\x02mine")

    result = apply_commit_to_working_tree(ws, before, after)

    assert "blob.bin" in result.skipped
    (ws / "blob.bin").write_bytes(b"\x00\x01\x02orig")
    check = subprocess.run(
        ["git", "apply", "--check", result.patch_path], cwd=ws, capture_output=True
    )
    assert check.returncode == 0, check.stderr


def test_aud009_error_on_one_path_does_not_stop_the_others(tmp_path: Path) -> None:
    ws = rb._workspace(
        tmp_path, "ws", git=True, files={"a.txt": "1\n", "b.txt": "2\n", "c.txt": "3\n"}
    )

    def edit(w: Path) -> None:
        (w / "a.txt").write_text("A\n", encoding="utf-8")
        (w / "b.txt").unlink()
        (w / "c.txt").write_text("C\n", encoding="utf-8")

    before, after = _step(ws, edit)
    os.chmod(ws / "b.txt", stat.S_IREAD)
    if os.name != "nt":
        os.chmod(
            ws, stat.S_IREAD | stat.S_IEXEC
        )  # deletion is a directory permission on POSIX
    try:
        result = apply_commit_to_working_tree(ws, before, after)
    finally:
        os.chmod(ws, stat.S_IRWXU)
        os.chmod(ws / "b.txt", stat.S_IWRITE | stat.S_IREAD)

    if os.name == "nt":
        assert (
            "b.txt" in result.skipped
            and "could not change it" in result.skipped["b.txt"]
        )
        assert set(result.applied) == {"a.txt", "c.txt"}


def test_aud010_operator_staged_entry_is_kept(tmp_path: Path) -> None:
    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    before, after = _step(
        ws, lambda w: (w / "a.txt").write_text("step\n", encoding="utf-8")
    )
    (ws / "other.txt").write_text("staged by me\n", encoding="utf-8")
    _git(ws, "add", "other.txt")
    stage_before = _git(ws, "ls-files", "--stage")

    result = apply_commit_to_working_tree(ws, before, after)

    assert result.applied == ("a.txt",)
    assert _git(ws, "ls-files", "--stage") == stage_before
    assert (ws / "a.txt").read_text(encoding="utf-8").strip() == "step"


def test_aud011_bracket_names_are_literal(tmp_path: Path) -> None:
    ws = rb._workspace(
        tmp_path,
        "ws",
        git=True,
        files={"lib/[ab].py": "x = 1\n", "lib/a.py": "y = 1\n"},
    )
    before, after = _step(
        ws, lambda w: (w / "lib" / "[ab].py").write_text("x = 2\n", encoding="utf-8")
    )
    (ws / "lib" / "a.py").write_text(
        "y = 99\n", encoding="utf-8"
    )  # operator edits a different file

    result = apply_commit_to_working_tree(ws, before, after)

    assert result.applied == ("lib/[ab].py",)
    assert result.skipped == {}


def test_aud012_listing_failure_is_not_success(tmp_path: Path) -> None:
    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    head = _git(ws, "rev-parse", "HEAD")

    result = apply_commit_to_working_tree(ws, head, "0" * 40)

    assert result.applied == ()
    assert "could not list" in result.skipped["(all paths)"]


def test_untracked_operator_file_is_protected_but_run_created_file_is_not(
    tmp_path: Path,
) -> None:
    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    (ws / "notes.txt").write_text("mine\n", encoding="utf-8")
    before, after = _step(
        ws, lambda w: (w / "notes.txt").write_text("model\n", encoding="utf-8")
    )

    mine = apply_commit_to_working_tree(ws, before, after)
    run_made = apply_commit_to_working_tree(
        ws, before, after, created_by_run=frozenset({"notes.txt"})
    )

    assert "untracked" in mine.skipped["notes.txt"]
    assert run_made.applied == ("notes.txt",)


# ---------------------------------------------------------------- G-020 constraints


def test_large_files_are_left_out_and_cannot_be_changed(tmp_path: Path) -> None:
    from ract.executor.worktree import take_snapshot

    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    (ws / "data.bin").write_bytes(b"x" * (3 * 1024 * 1024))

    snap = take_snapshot(ws)

    assert snap.left_out == ("data.bin",)
    assert (
        "data.bin"
        not in _git(ws, "ls-tree", "-r", "--name-only", snap.sha).splitlines()
    )
    result = apply_commit_to_working_tree(
        ws, snap.sha, snap.sha, left_out=frozenset(snap.left_out)
    )
    assert result.applied == ()


def test_change_to_a_left_out_or_secret_path_is_refused(tmp_path: Path) -> None:
    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    before, after = _step(
        ws, lambda w: (w / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    )

    result = apply_commit_to_working_tree(ws, before, after)

    assert "left this file out" in result.skipped[".env"]
    assert not (ws / ".env").exists()


def test_crlf_file_the_operator_did_not_touch_is_applied(tmp_path: Path) -> None:
    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\ntwo\n"})
    _git(ws, "config", "core.autocrlf", "true")
    (ws / "a.txt").unlink()
    _git(ws, "checkout", "--", "a.txt")  # rewritten with CRLF under autocrlf
    assert b"\r\n" in (ws / "a.txt").read_bytes()
    before, after = _step(
        ws, lambda w: (w / "a.txt").write_text("one\nthree\n", encoding="utf-8")
    )

    result = apply_commit_to_working_tree(ws, before, after)

    assert result.applied == ("a.txt",), result.skipped
    assert (ws / "a.txt").read_bytes().replace(b"\r\n", b"\n") == b"one\nthree\n"


def test_failed_snapshot_leaves_no_temporary_index(tmp_path: Path) -> None:
    import tempfile

    import pytest

    from ract.executor.worktree import WorktreeError, take_snapshot

    import ract.executor.worktree as wt

    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    (ws / "a.txt").write_text("changed\n", encoding="utf-8")
    # A temporary directory of this test's own: the system one is shared
    # with any other test run on the machine, whose live snapshots made
    # this fail under a concurrent run (full gate on the S-026 follow-up).
    temp = tmp_path / "temp"
    temp.mkdir()
    before: set[str] = set()
    real_run = subprocess.run

    def stalled_add(args: list[str], **kwargs: Any) -> Any:
        if "add" in args and "-u" in args:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout") or 0)
        return real_run(args, **kwargs)

    mp = pytest.MonkeyPatch()
    mp.setattr(wt.subprocess, "run", stalled_add)
    mp.setattr(tempfile, "tempdir", str(temp))
    try:
        with pytest.raises(WorktreeError, match="took longer"):
            take_snapshot(ws)
    finally:
        mp.undo()

    assert {p.name for p in temp.glob("ract-snapshot-*")} == before


def test_normal_run_prints_no_in_place_note(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    _commit_all(ws)

    result = _ract(ws, "fix add")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "writes directly into your files" not in result.stdout


# ---------------------------------------------------------------- S-011c limits


def _many_untracked(ws: Path, count: int) -> None:
    for i in range(count):
        d = ws / "gen" / f"d{i // 100:03d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"f{i:05d}.txt").write_text(f"{i}\n", encoding="utf-8")


def test_snapshot_of_a_repository_with_no_commits_and_no_tracked_files(
    tmp_path: Path,
) -> None:
    from ract.executor.worktree import take_snapshot

    ws = tmp_path / "fresh"
    ws.mkdir()
    _git(ws, "init", "-q")
    (ws / "main.py").write_text("print(1)\n", encoding="utf-8")

    snap = take_snapshot(ws)

    assert _git(ws, "ls-tree", "-r", "--name-only", snap.sha) == "main.py"
    assert snap.left_out == ()


def test_untracked_count_cap_keeps_shallow_files_and_names_the_rest(
    tmp_path: Path,
) -> None:
    from ract.executor.worktree import take_snapshot

    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    (ws / "top.py").write_text("x = 1\n", encoding="utf-8")
    _many_untracked(ws, 30)

    snap = take_snapshot(ws, max_untracked=10)

    in_snapshot = _git(ws, "ls-tree", "-r", "--name-only", snap.sha).splitlines()
    assert "top.py" in in_snapshot  # shallowest first
    assert len(snap.over_count) == 21
    assert set(snap.over_count).isdisjoint(in_snapshot)
    notice = snap.notice()
    assert "21 files left out" in notice
    assert "21 past the first 10 untracked files" in notice
    assert ".gitignore" in notice
    assert "and 11 more" in notice


def test_time_budget_leaves_untracked_out_but_keeps_tracked_changes(
    tmp_path: Path,
) -> None:
    from ract.executor.worktree import take_snapshot

    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    (ws / "a.txt").write_text("edited\n", encoding="utf-8")
    _many_untracked(ws, 5)

    snap = take_snapshot(ws, budget=0.0)

    assert len(snap.over_time) == 5
    assert _git(ws, "show", f"{snap.sha}:a.txt") == "edited"
    assert "5 not reached in 0 s" in snap.notice()


def test_left_out_untracked_file_cannot_be_changed_by_a_step(tmp_path: Path) -> None:
    from ract.executor.worktree import take_snapshot

    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    _many_untracked(ws, 3)
    snap = take_snapshot(ws, max_untracked=1)
    victim = snap.over_count[0]
    before, after = _step(
        ws, lambda w: (w / victim).write_text("step wrote this\n", encoding="utf-8")
    )

    result = apply_commit_to_working_tree(
        ws, before, after, left_out=frozenset(snap.left_out)
    )

    assert victim in result.skipped
    assert (ws / victim).read_text(encoding="utf-8") != "step wrote this\n"


def test_progress_lines_only_after_two_seconds(tmp_path: Path) -> None:
    import ract.executor.worktree as wt

    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    _many_untracked(ws, 6)
    lines: list[str] = []
    mp = __import__("pytest").MonkeyPatch()
    mp.setattr(wt, "_UNTRACKED_BATCH", 2)
    mp.setattr(wt, "_PROGRESS_AFTER_SECONDS", 0.0)
    try:
        wt.take_snapshot(ws, progress=lines.append)
    finally:
        mp.undo()
    assert lines and lines[-1] == (
        "snapshotting your working tree: 6 of 6 untracked files"
    )
    quiet: list[str] = []
    wt.take_snapshot(ws, progress=quiet.append)
    assert quiet == []  # a fast snapshot says nothing


def test_run_prints_the_left_out_notice(tmp_path: Path, fake_model_server: Any) -> None:
    from ract.executor.worktree import SNAPSHOT_MAX_UNTRACKED

    server = fake_model_server("baseline_j4_today")
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    _commit_all(ws)
    _many_untracked(ws, SNAPSHOT_MAX_UNTRACKED + 5)

    result = _ract(ws, "fix add")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "5 files left out of this run's snapshot" in result.stdout
    assert "Add generated, vendored or large files to .gitignore." in result.stdout
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")


def test_a_failed_step_leaves_no_step_branch(
    tmp_path: Path, fake_model_server: Any
) -> None:
    """G-033: with no post-condition the loop committed every step whose
    runner returned, so a failed step left an empty "rootact step" commit on
    a rootact/step/* branch. The executor's success is now a post-condition;
    a failed step rolls back and its branch is deleted."""
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {
                        "reply": {
                            "kind": "text",
                            "content": _plan(("Fix add", "src/calc.py")),
                        }
                    },
                    {"reply": {"kind": "fault", "fault": "http_500"}, "repeat": True},
                ]
            }
        )
    )
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    (ws / "ract.yaml").write_text(
        (ws / "ract.yaml")
        .read_text(encoding="utf-8")
        .replace(
            "    model: fake-coder\n", "    model: fake-coder\n    max_retries: 0\n"
        ),
        encoding="utf-8",
    )
    _commit_all(ws)

    result = _ract(ws, "fix add")

    assert result.returncode != 0
    assert _step_branches(ws) == [], result.stdout + result.stderr
    assert _git(ws, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_a_batch_killed_at_the_budget_leaves_a_usable_snapshot(
    tmp_path: Path,
) -> None:
    """Full-suite gate failure: under load the budget killed a `git add`
    batch, its index.lock stayed beside the temporary index, and write-tree
    failed ("could not write the snapshot tree"), so the run failed."""
    import pytest

    import ract.executor.worktree as wt

    ws = rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})
    (ws / "a.txt").write_text("edited\n", encoding="utf-8")
    _many_untracked(ws, 5)
    real_run = subprocess.run

    def killed_batch(args: list[str], **kwargs: Any) -> Any:
        if "--pathspec-from-file=-" in args:
            index = kwargs["env"]["GIT_INDEX_FILE"]
            Path(index + ".lock").write_bytes(b"")  # what a killed git leaves
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout") or 0)
        return real_run(args, **kwargs)

    mp = pytest.MonkeyPatch()
    mp.setattr(wt.subprocess, "run", killed_batch)
    try:
        snap = wt.take_snapshot(ws)
    finally:
        mp.undo()

    assert len(snap.over_time) == 5
    assert _git(ws, "show", f"{snap.sha}:a.txt") == "edited"
