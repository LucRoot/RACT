"""G-038: the operator's git hooks do not run on RACT's step transactions.

Step worktrees share the repository's hooks. A failing pre-commit hook
failed every step ("git commit failed"), and post-checkout and post-commit
hooks ran the operator's code on RACT's internal commits.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.ux import run_baseline as rb


def _hook(path: Path, marker: Path, exit_code: int) -> None:
    path.write_text(
        f"#!/bin/sh\necho ran >> '{marker.as_posix()}'\nexit {exit_code}\n",
        encoding="utf-8",
        newline="\n",
    )
    path.chmod(0o755)


@pytest.mark.parametrize("where", ["core.hooksPath", ".git/hooks"])
def test_operator_hooks_do_not_run_on_step_commits(
    tmp_path: Path, fake_model_server: Any, where: str
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    ident = ["-c", "user.name=d", "-c", "user.email=d@example.invalid"]
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", *ident, "commit", "-q", "-m", "c"], cwd=ws, check=True)

    hooks = tmp_path / "hooks" if where == "core.hooksPath" else ws / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    markers = {name: tmp_path / f"{name}.ran" for name in ("pre", "post", "checkout")}
    _hook(hooks / "pre-commit", markers["pre"], 1)  # would fail every step
    _hook(hooks / "post-commit", markers["post"], 0)
    _hook(hooks / "post-checkout", markers["checkout"], 0)
    if where == "core.hooksPath":
        subprocess.run(
            ["git", "config", "core.hooksPath", str(hooks)], cwd=ws, check=True
        )

    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    # A machine-wide core.hooksPath (some setups have one) makes git ignore
    # .git/hooks; an empty global config keeps the case under test real.
    empty_global = tmp_path / "empty.gitconfig"
    empty_global.write_text("", encoding="utf-8")
    env["GIT_CONFIG_GLOBAL"] = str(empty_global)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "--config",
            "ract.yaml",
            "--yolo",
            "fix add",
        ],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=env,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "return a + b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")
    ran = [name for name, marker in markers.items() if marker.exists()]
    assert ran == [], f"operator hooks ran on RACT's step transaction: {ran}"
