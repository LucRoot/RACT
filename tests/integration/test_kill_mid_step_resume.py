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
