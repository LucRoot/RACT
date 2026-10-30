"""ADR-0049 D13 (B-070): a run killed during step 2 of 2 resumes from its checkpoint.

The run is a real `ract` process against the fake model server. Step 2's
model call never answers; the test waits until the checkpoint names step 2
as in progress, kills the process, and resumes with `--session <id>
--resume` against a new server that has only step 2's reply. Requests are
counted at that server, so a rerun of the plan or of step 1 would show.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from ract import run_checkpoint as rc
from ract.manager import Plan, Step
from tests.fixtures.fake_model_server import Scenario
from tests.ux import run_baseline as rb

UTIL = "def util():\n    return 1\n"
MORE = 'GREETING = "hello"\nNAMES = ["ada", "grace", "linus"]\n'


@pytest.fixture
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))
    return home


def _env(home: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["LOCALAPPDATA"] = str(home)
    env["XDG_STATE_HOME"] = str(home)
    return env


def _cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", "--yolo", *args]


def _ract(ws: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _cmd(*args),
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        env=_env(home),
        stdin=subprocess.DEVNULL,
    )


def _git(ws: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True
    ).stdout


def _plan_reply() -> str:
    return json.dumps(
        {
            "assumption": "a",
            "confidence": 0.9,
            "steps": [
                {
                    "action": "Create util",
                    "provider_hint": "local",
                    "expected_artifact": "src/util.py",
                },
                {
                    "action": "Create more",
                    "provider_hint": "local",
                    "expected_artifact": "src/more.py",
                },
            ],
        }
    )


def _text(content: str) -> dict[str, Any]:
    return {"reply": {"kind": "text", "content": content}}


def _checkpoints(ws: Path) -> list[Path]:
    folder = rc.runs_dir(ws)
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def _kill_during_step_2(
    tmp_path: Path, home: Path, fake_model_server: Any, *, git: bool
) -> tuple[Path, str, dict[str, Any]]:
    """Run a two-step plan, kill it while step 2 waits on the model."""
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    _text(_plan_reply()),
                    _text(UTIL),
                    {
                        "reply": {
                            "kind": "fault",
                            "fault": "never_respond",
                            "hold_seconds": 600,
                        }
                    },
                ]
            }
        )
    )
    ws = rb._workspace(tmp_path, "ws", git=git, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    if git:
        identity = ["-c", "user.name=d", "-c", "user.email=d@example.invalid"]
        _git(ws, "add", "-A")
        _git(ws, *identity, "commit", "-q", "-m", "c")
    proc = subprocess.Popen(
        _cmd("make util and more"),
        cwd=ws,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_env(home),
        stdin=subprocess.DEVNULL,
    )
    seen: dict[str, Any] = {}
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            assert proc.poll() is None, "the run ended before step 2 was reached"
            found = _checkpoints(ws)
            if found and len(server.chat_requests) >= 3:
                data = json.loads(found[0].read_text(encoding="utf-8"))
                if (data.get("in_progress") or {}).get("n") == 2:
                    seen = data
                    break
            time.sleep(0.2)
        assert seen, "the checkpoint never named step 2 as in progress"
    finally:
        proc.kill()
        proc.wait(timeout=30)
    return ws, found[0].stem, seen


def _resume(ws: Path, home: Path, run_id: str, fake_model_server: Any):
    server = fake_model_server(Scenario.from_dict({"turns": [_text(MORE)]}))
    rb._configure(ws, server.base_url, "fake-coder")
    result = _ract(ws, home, "--session", run_id, "--resume")
    return server, result


@pytest.mark.parametrize("git", [True, False], ids=["worktree", "direct"])
def test_a_checkpoint_exists_after_step_1(
    tmp_path: Path, state_home: Path, fake_model_server: Any, git: bool
) -> None:
    ws, run_id, seen = _kill_during_step_2(
        tmp_path, state_home, fake_model_server, git=git
    )

    assert seen["finished"] == [1]
    assert seen["run"] == run_id
    assert [s["target"] for s in seen["plan"]["steps"]] == [
        "src/util.py",
        "src/more.py",
    ]
    # Recorded before step 2 touched a file: it has written nothing yet.
    assert seen["in_progress"]["files"] == []
    assert (ws / "src" / "util.py").read_text(encoding="utf-8") == UTIL
    assert not (ws / "src" / "more.py").exists()
    if git:
        assert seen["in_progress"]["worktree"]


@pytest.mark.parametrize("git", [True, False], ids=["worktree", "direct"])
def test_resume_never_reruns_a_finished_step(
    tmp_path: Path, state_home: Path, fake_model_server: Any, git: bool
) -> None:
    ws, run_id, _ = _kill_during_step_2(
        tmp_path, state_home, fake_model_server, git=git
    )

    server, result = _resume(ws, state_home, run_id, fake_model_server)

    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    # One request: step 2. No planning call, no second call for step 1.
    assert len(server.chat_requests) == 1, out
    assert "step 1 done earlier, not run again" in out
    assert "step 2 was interrupted" in out
    assert (ws / "src" / "util.py").read_text(encoding="utf-8") == UTIL
    assert (ws / "src" / "more.py").read_text(encoding="utf-8") == MORE


def test_no_half_written_file_remains_after_resume(
    tmp_path: Path, state_home: Path, fake_model_server: Any
) -> None:
    ws, run_id, _ = _kill_during_step_2(
        tmp_path, state_home, fake_model_server, git=True
    )

    _, result = _resume(ws, state_home, run_id, fake_model_server)

    assert result.returncode == 0, result.stdout + result.stderr
    # The killed step's worktree and branch are gone; one branch per step.
    worktrees = [
        line
        for line in _git(ws, "worktree", "list", "--porcelain").splitlines()
        if line.startswith("worktree ")
    ]
    assert len(worktrees) == 1
    branches = _git(ws, "branch", "--list", "rootact/step/*").split()
    assert len(branches) == 2
    # The finished run leaves no checkpoint and no temporary file.
    folder = rc.runs_dir(ws)
    assert not folder.exists() or list(folder.iterdir()) == []
    assert not (ws / ".ract" / "pending").exists()


def _workspace_bytes(ws: Path) -> dict[str, bytes]:
    return {
        p.relative_to(ws).as_posix(): p.read_bytes()
        for p in sorted(ws.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(ws).parts
    }


def _planted(ws: Path) -> Path:
    plan = Plan(
        assumption="a",
        confidence=0.9,
        steps=[
            Step(
                action="Create util",
                provider_hint="local",
                expected_artifact="src/util.py",
            ),
            Step(
                action="Create more",
                provider_hint="local",
                expected_artifact="src/more.py",
            ),
        ],
    )
    checkpoint = rc.RunCheckpoint(ws, "r1", "make util and more")
    checkpoint.plan_ready(plan)
    checkpoint.step_started(1)
    checkpoint.step_finished(1)
    return rc.checkpoint_path(ws, "r1")


def _truncate(path: Path, ws: Path) -> None:
    raw = path.read_bytes()
    path.write_bytes(raw[: len(raw) // 2])


def _oversize(path: Path, ws: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["intent"] = "x" * (rc.MAX_CHECKPOINT_BYTES + 1)
    path.write_text(json.dumps(data), encoding="utf-8")


def _foreign(path: Path, ws: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["root"] = str(ws.parent / "another")
    path.write_text(json.dumps(data), encoding="utf-8")


def _link(path: Path, ws: Path) -> None:
    target = ws.parent / "elsewhere.json"
    target.write_bytes(path.read_bytes())
    path.unlink()
    try:
        os.symlink(target, path)
    except OSError:
        pytest.skip("symbolic links need a privilege this machine does not grant")


def _hash_mismatch(path: Path, ws: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["plan"]["steps"][1]["action"] = "Delete the tests"
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize(
    "damage",
    [_truncate, _oversize, _foreign, _link],
    ids=["corrupted", "oversized", "foreign", "linked"],
)
def test_a_corrupted_oversized_linked_or_foreign_checkpoint_is_refused_and_never_run(
    tmp_path: Path, state_home: Path, fake_model_server: Any, damage
) -> None:
    server = fake_model_server(Scenario.from_dict({"turns": [_text(MORE)]}))
    ws = rb._workspace(tmp_path, "ws", git=False, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    damage(_planted(ws), ws)
    before = _workspace_bytes(ws)

    result = _ract(ws, state_home, "--session", "r1", "--resume")

    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "not trusted" in out
    assert server.chat_requests == []
    assert _workspace_bytes(ws) == before


def test_a_plan_hash_mismatch_is_not_trusted(
    tmp_path: Path, state_home: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(Scenario.from_dict({"turns": [_text(MORE)]}))
    ws = rb._workspace(tmp_path, "ws", git=False, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    _hash_mismatch(_planted(ws), ws)
    before = _workspace_bytes(ws)

    result = _ract(ws, state_home, "--session", "r1", "--resume")

    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "plan_hash" in out
    assert server.chat_requests == []
    assert _workspace_bytes(ws) == before


def test_a_run_that_stops_early_prints_how_to_resume_it(
    tmp_path: Path, state_home: Path, fake_model_server: Any
) -> None:
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    _text(_plan_reply()),
                    _text(UTIL),
                    {"repeat": True, "reply": {"kind": "fault", "fault": "http_500"}},
                ]
            }
        )
    )
    ws = rb._workspace(tmp_path, "ws", git=False, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")

    result = _ract(ws, state_home, "make util and more")

    assert result.returncode != 0
    [path] = _checkpoints(ws)
    assert f"ract run --session {path.stem} --resume" in result.stderr
