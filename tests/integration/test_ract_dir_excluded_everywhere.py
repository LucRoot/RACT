"""B-069 (D-038): every command that writes `.ract/` keeps it out of `git status`.

S-016 put `.ract/` in the clone's local exclude file on every `run_ract`.
Three commands write `.ract/` without going through it: `ract consolidate`,
`ract memory init` and `ract run --loop`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def _repo(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "src").mkdir(parents=True)
    body = "def f(x):\n    y = x + 1\n    return y * 2\n"
    (ws / "src" / "a.py").write_text(body, encoding="utf-8")
    (ws / "src" / "b.py").write_text(body.replace("f(", "g("), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run([*GIT, "add", "-A"], cwd=ws, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=ws, check=True)
    return ws


def _ract(ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
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


def _status(ws: Path) -> str:
    return subprocess.run(
        ["git", "status", "--short"], cwd=ws, capture_output=True, text=True, check=True
    ).stdout


@pytest.mark.parametrize(
    "args",
    [
        ["consolidate", "scan", "--project-dir", "."],
        ["memory", "init", "."],
    ],
    ids=["consolidate", "memory-init"],
)
def test_the_command_leaves_git_status_clean(tmp_path: Path, args: list[str]) -> None:
    ws = _repo(tmp_path)

    _ract(ws, *args)

    if not (ws / ".ract").exists():
        pytest.skip(f"`ract {' '.join(args)}` wrote no .ract/ here")
    assert ".ract" not in _status(ws), _status(ws)


def test_loop_excludes_ract_before_the_loop_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ract import cli
    from ract import trust

    ws = _repo(tmp_path)
    (ws / "ract.yaml").write_text("project:\n  name: demo\n", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(trust, "confirm_loop", lambda *a, **k: True)

    def excluded(repo: Any) -> bool:
        calls.append("exclude")
        return True

    class Stop(Exception):
        pass

    def loop_controller(*a: Any, **k: Any) -> Any:
        calls.append("loop")
        raise Stop

    monkeypatch.setattr("ract.executor.worktree.ensure_ract_dir_excluded", excluded)
    monkeypatch.setattr("ract.loop_controller.LoopController", loop_controller)
    monkeypatch.chdir(ws)

    with pytest.raises(Stop):
        cli.main(["run", "--config", "ract.yaml", "--loop", "--yolo", "--", "fix it"])

    assert calls == ["exclude", "loop"]
