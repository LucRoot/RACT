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
