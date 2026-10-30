"""S-016: RACT's bookkeeping stays out of the operator's way.

- `.ract/` is added to the clone-local `.git/info/exclude` at first use, so
  it no longer shows as untracked; the operator's `.gitignore` is untouched.
- `ract doctor` lists RACT's `rootact/step/*` branches, and deletes old ones
  only when asked with `--prune-step-branches DAYS`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ract.executor.worktree import (
    ensure_ract_dir_excluded,
    list_step_branches,
    prune_step_branches,
)
from tests.ux import run_baseline as rb


def _git(ws: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    return rb._workspace(tmp_path, "ws", git=True, files={"a.txt": "one\n"})


def _branch_at_age(ws: Path, name: str, days: float) -> None:
    stamp = int(time.time() - days * 86400)
    env = dict(os.environ)
    env["GIT_COMMITTER_DATE"] = f"{stamp} +0000"
    env["GIT_AUTHOR_DATE"] = f"{stamp} +0000"
    tree = _git(ws, "rev-parse", "HEAD^{tree}")
    sha = _git(
        ws,
        "-c",
        "user.name=d",
        "-c",
        "user.email=d@example.invalid",
        "commit-tree",
        tree,
        "-p",
        "HEAD",
        "-m",
        name,
        env=env,
    )
    _git(ws, "branch", name, sha)


def test_exclude_is_added_once_and_ract_leaves_git_status(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    (ws / ".ract").mkdir()
    (ws / ".ract" / "state.json").write_text("{}", encoding="utf-8")
    assert ".ract/" in _git(ws, "status", "--porcelain")

    assert ensure_ract_dir_excluded(ws) is True
    assert ensure_ract_dir_excluded(ws) is False

    assert ".ract" not in _git(ws, "status", "--porcelain")
    exclude = (ws / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.count(".ract/") == 1
    assert not (ws / ".gitignore").exists()


def test_exclude_works_in_a_linked_worktree(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    linked = tmp_path / "linked"
    _git(ws, "worktree", "add", "-q", str(linked), "-b", "side")
    assert (linked / ".git").is_file()
    (linked / ".ract").mkdir()
    (linked / ".ract" / "x").write_text("1", encoding="utf-8")

    assert ensure_ract_dir_excluded(linked) is True
    assert ".ract" not in _git(linked, "status", "--porcelain")


def test_exclude_is_a_no_op_outside_git(tmp_path: Path) -> None:
    assert ensure_ract_dir_excluded(tmp_path) is False


def test_prune_deletes_only_old_step_branches(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    _branch_at_age(ws, "rootact/step/old", 30)
    _branch_at_age(ws, "rootact/step/new", 1)
    _branch_at_age(ws, "feature/old-but-mine", 30)

    assert [b.name for b in list_step_branches(ws)] == [
        "rootact/step/old",
        "rootact/step/new",
    ]
    assert prune_step_branches(ws, 14) == ["rootact/step/old"]

    branches = _git(ws, "branch", "--format=%(refname:short)").splitlines()
    assert "rootact/step/new" in branches
    assert "feature/old-but-mine" in branches
    assert "rootact/step/old" not in branches


def test_run_adds_the_exclude_and_doctor_lists_step_branches(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
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
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["NO_COLOR"] = "1"
    env["COLUMNS"] = "200"

    def ract(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "ract.cli", *args],
            cwd=ws,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            env=env,
            stdin=subprocess.DEVNULL,
        )

    assert (
        ract(
            "--config",
            "ract.yaml",
            "--yolo",
            "tests/test_calc.py::test_add fails, fix it",
        ).returncode
        == 0
    )
    assert ".ract" not in _git(ws, "status", "--porcelain")

    data = json.loads(ract("doctor", "--config", "ract.yaml", "--json").stdout)
    assert data["step_branches"]["count"] >= 1
    text = " ".join(ract("doctor", "--config", "ract.yaml").stdout.split())
    assert "rootact/step/* branch(es)" in text
    assert "--prune-step-branches DAYS" in text

    pruned = json.loads(
        ract(
            "doctor", "--config", "ract.yaml", "--json", "--prune-step-branches", "0"
        ).stdout
    )
    assert pruned["step_branches"]["count"] == 0
    assert pruned["step_branches"]["pruned"]
