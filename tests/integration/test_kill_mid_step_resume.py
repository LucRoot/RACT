"""B-066: a three-step run killed in the middle of step 2 resumes.

The landed checkpoint test (``test_run_checkpoint_resume.py``, B-070) kills a
two-step run with ``proc.kill()``, which stops only the parent process. This
file adds the three-step plan of the B-066 card, a process-tree kill
(``taskkill /T /F`` on Windows, SIGKILL to the process group elsewhere), and
resumes on a new server that has only the replies the rerun needs. A rerun of
step 1 or of the plan would show in that server's request count.
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
from tests.fixtures.fake_model_server import Scenario
from tests.integration._process_tree import can_kill_tree, kill_tree
from tests.ux import run_baseline as rb

pytestmark = pytest.mark.skipif(
    not can_kill_tree(),
    reason="no process-tree kill on this platform, so the kill-and-resume tests cannot run",
)

CALC = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"
NOTES = 'NOTE = "two"\n'
DRAFT = b"my unsaved draft\r\nsecond line\x00 not committed\n"
TESTS = 'from src.notes import NOTE\n\n\ndef test_note():\n    assert NOTE == "two"\n'
GIT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
STEP1 = "Task: Fix add"
STEP2 = "Task: Add src/notes.py"
STEP3 = "Task: Add tests/test_notes.py"


def _text(content: str) -> dict[str, Any]:
    return {"reply": {"kind": "text", "content": content}}


def _plan() -> str:
    steps = [
        ("Fix add() in src/calc.py so it adds", "src/calc.py"),
        ("Add src/notes.py with the NOTE constant", "src/notes.py"),
        ("Add tests/test_notes.py that checks NOTE", "tests/test_notes.py"),
    ]
    return json.dumps(
        {
            "assumption": "three steps",
            "confidence": 0.9,
            "steps": [
                {"action": a, "provider_hint": "local", "expected_artifact": p}
                for a, p in steps
            ],
        }
    )


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
    return [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", *args]


def _checkpoints(ws: Path) -> list[Path]:
    folder = rc.runs_dir(ws)
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def _count(server: Any, task: str) -> int:
    return sum(task in str(r.body) for r in server.chat_requests)


def _kill_in_step_two(
    tmp_path: Path, home: Path, fake_model_server: Any
) -> tuple[Path, str]:
    """Run the three-step plan and kill it while step 2 waits on the model."""
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    _text(_plan()),
                    _text(CALC.replace("a - b", "a + b", 1)),
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
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    subprocess.run(["git", *GIT, "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", *GIT, "commit", "-q", "-m", "c"], cwd=ws, check=True)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "draft.md").write_bytes(DRAFT)  # the user's own uncommitted work
    proc = subprocess.Popen(
        _cmd("fix add"),
        cwd=ws,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_env(home),
        stdin=subprocess.DEVNULL,
        start_new_session=sys.platform != "win32",
    )
    try:
        deadline = time.monotonic() + 180
        while True:
            assert proc.poll() is None, "the run ended before step 2 was reached"
            assert time.monotonic() < deadline, "step 2 never reached the server"
            found = _checkpoints(ws)
            if found and len(server.chat_requests) >= 3:
                data = json.loads(found[0].read_text(encoding="utf-8"))
                if (data.get("in_progress") or {}).get("n") == 2:
                    break
            time.sleep(0.2)
    finally:
        kill_tree(proc)
    return ws, found[0].stem


def test_kill_in_step_two_then_resume_finishes_without_rerunning_step_one(
    tmp_path: Path, state_home: Path, fake_model_server: Any
) -> None:
    ws, run_id = _kill_in_step_two(tmp_path, state_home, fake_model_server)
    assert not (ws / "src" / "notes.py").exists()

    resume = fake_model_server(
        Scenario.from_dict({"turns": [_text(NOTES), _text(TESTS)]})
    )
    rb._configure(ws, resume.base_url, "fake-coder")
    done = subprocess.run(
        _cmd("--session", run_id, "--resume"),
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=_env(state_home),
        stdin=subprocess.DEVNULL,
    )

    assert done.returncode == 0, done.stderr[-400:]
    assert "Traceback" not in done.stdout + done.stderr
    assert (ws / "src" / "notes.py").read_text(encoding="utf-8") == NOTES
    assert (ws / "tests" / "test_notes.py").read_text(encoding="utf-8") == TESTS
    assert (ws / "docs" / "draft.md").read_bytes() == DRAFT
    assert _count(resume, STEP1) == 0, "step 1 was rerun"
    assert len(resume.chat_requests) == 2, "only step 2 and step 3 should be asked"


def test_resume_with_no_run_to_continue_says_so_and_asks_the_model_nothing(
    tmp_path: Path, state_home: Path, fake_model_server: Any
) -> None:
    # A run that never checkpointed (killed before step 1) or that finished
    # (its checkpoint is removed) leaves nothing to resume: the resume must
    # say so in plain words and send no request.
    server = fake_model_server(Scenario.from_dict({"turns": [_text(NOTES)]}))
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")

    done = subprocess.run(
        _cmd("--session", "never-checkpointed", "--resume"),
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=_env(state_home),
        stdin=subprocess.DEVNULL,
    )

    output = (done.stdout + done.stderr).lower()
    assert done.returncode != 0
    assert "traceback" not in output
    assert "not found" in output
    assert server.chat_requests == []


def test_resume_leaves_no_step_branch_or_worktree_behind(
    tmp_path: Path, state_home: Path, fake_model_server: Any
) -> None:
    ws, run_id = _kill_in_step_two(tmp_path, state_home, fake_model_server)
    before = _git_lines(ws, "branch", "--list")
    worktrees_before = _git_lines(ws, "worktree", "list")

    resume = fake_model_server(
        Scenario.from_dict({"turns": [_text(NOTES), _text(TESTS)]})
    )
    rb._configure(ws, resume.base_url, "fake-coder")
    done = subprocess.run(
        _cmd("--session", run_id, "--resume"),
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=_env(state_home),
        stdin=subprocess.DEVNULL,
    )

    assert done.returncode == 0, done.stderr[-400:]
    assert "already exists" not in (done.stdout + done.stderr)
    assert len(worktrees_before) >= 1
    assert len(_git_lines(ws, "worktree", "list")) == 1, "a worktree was left behind"
    after = _git_lines(ws, "branch", "--list")
    # A clean run keeps one step branch per step (three here). The killed
    # step's branch is reset or reused, so the count stays at three.
    steps = [b for b in after if b.startswith("rootact/step/")]
    assert len(steps) == 3, (
        f"expected one branch per step, found {steps} (before: {before})"
    )


def _git_lines(ws: Path, *args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=ws, capture_output=True, text=True, check=True
    ).stdout
    return [line.strip(" *+") for line in out.splitlines() if line.strip()]


WRAPPER = """\
import os
import pathlib
import sys

from ract import cli

TARGET = {target!r}
original = pathlib.Path.write_text
seen = {{"n": 0}}


def half_write(self, data, encoding=None, errors=None, newline=None):
    # Kill the run in the middle of writing the target: half the bytes are on
    # disk, flushed, and then the process exits without any cleanup.
    if self.name == TARGET:
        seen["n"] += 1
        if seen["n"] == 1:
            with open(self, "w", encoding="utf-8") as f:
                f.write(data[: len(data) // 2])
                f.flush()
                os.fsync(f.fileno())
            os._exit(9)
    return original(self, data, encoding=encoding, errors=errors, newline=newline)


pathlib.Path.write_text = half_write
sys.exit(cli.main(sys.argv[1:]))
"""


def test_kill_during_a_file_write_leaves_no_truncated_file(
    tmp_path: Path, state_home: Path, fake_model_server: Any
) -> None:
    # The wrapper stops the run while src/notes.py is half written, the way a
    # power cut would. No sleep: the write itself is the kill point.
    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    _text(_plan()),
                    _text(CALC.replace("a - b", "a + b", 1)),
                    _text(NOTES),
                ]
            }
        )
    )
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    subprocess.run(["git", *GIT, "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", *GIT, "commit", "-q", "-m", "c"], cwd=ws, check=True)
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "draft.md").write_bytes(DRAFT)
    wrapper = tmp_path / "killing_wrapper.py"
    wrapper.write_text(WRAPPER.format(target="notes.py"), encoding="utf-8")

    killed = subprocess.run(
        [sys.executable, str(wrapper), "--config", "ract.yaml", "fix add"],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=_env(state_home),
        stdin=subprocess.DEVNULL,
    )

    assert killed.returncode == 9, killed.stderr[-400:]
    found = [p for p in list(ws.rglob("notes.py")) + list(state_home.rglob("notes.py"))]
    Path(
        "C:/Users/rootl/AppData/Local/Temp/claude/C--RootClaw/4c0c3abd-c6e9-467b-a8eb-a9df19316368/scratchpad/b066/found.txt"
    ).write_text(repr([str(p) for p in found]), encoding="utf-8")
    assert found, "no notes.py was written before the kill"
    assert all(p.read_text(encoding="utf-8") != NOTES for p in found[:1]), (
        "the kill should leave a half-written file"
    )
    [checkpoint] = _checkpoints(ws)

    resume = fake_model_server(
        Scenario.from_dict({"turns": [_text(NOTES), _text(TESTS)]})
    )
    rb._configure(ws, resume.base_url, "fake-coder")
    done = subprocess.run(
        _cmd("--session", checkpoint.stem, "--resume"),
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=_env(state_home),
        stdin=subprocess.DEVNULL,
    )

    assert done.returncode == 0, done.stderr[-400:]
    assert (ws / "src" / "notes.py").read_text(encoding="utf-8") == NOTES
    truncated = [
        p for p in ws.rglob("notes.py") if p.read_text(encoding="utf-8") != NOTES
    ]
    assert truncated == [], f"a truncated notes.py remains: {truncated}"
    assert (ws / "docs" / "draft.md").read_bytes() == DRAFT
    assert _count(resume, STEP2) == 1, "the interrupted step should be asked once"
