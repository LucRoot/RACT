"""B-072: the two three-step plan scenarios run end to end through `ract`.

The fake model server plays the plan and each step's file. The success run
writes three files with four requests (plan, then one per step). The failing
run's step 2 gets an empty reply: step 2 is refused with a message, step 3 is
never requested, and only step 1's file exists.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


from tests.fixtures.fake_model_server import FakeModelServer
from tests.ux import run_baseline as rb


def _run(
    scenario: str, tmp_path: Path
) -> tuple[subprocess.CompletedProcess[str], FakeModelServer, Path]:
    server = FakeModelServer(scenario).start()
    ws = tmp_path / "ws"
    ws.mkdir()
    rb._configure(ws, server.base_url, "fake-coder")
    (ws / "src").mkdir()
    (ws / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (ws / "tests").mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run([*git, "add", "-A"], cwd=ws, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], cwd=ws, check=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ract.cli", "--yolo", "fix add"],
            cwd=ws,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
    finally:
        server.stop()
    return proc, server, ws


def test_a_three_step_plan_writes_three_files(tmp_path: Path) -> None:
    proc, server, ws = _run("plan_three_steps", tmp_path)
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "Traceback" not in proc.stdout + proc.stderr
    assert (ws / "src" / "notes.py").read_text(encoding="utf-8") == 'NOTE = "two"\n'
    assert (ws / "tests" / "test_notes.py").is_file()
    assert "def add(a, b):\n    return a + b" in (ws / "src" / "calc.py").read_text(
        encoding="utf-8"
    )
    assert len(server.chat_requests) == 4  # the plan, then one request per step


def test_an_empty_step_fails_and_the_next_step_is_never_asked(tmp_path: Path) -> None:
    proc, server, ws = _run("plan_three_steps_fail_2", tmp_path)
    assert proc.returncode == 1
    assert "Traceback" not in proc.stdout + proc.stderr
    # B-073: the substrate runs each step as a one-step plan; the message
    # names the step's number in the whole plan, and a hint line follows.
    assert "Step 2 produced no content for src/notes.py" in proc.stderr
    assert "Step 1 produced" not in proc.stderr
    hints = [line for line in proc.stderr.splitlines() if "hint:" in line]
    assert hints and "empty reply" in hints[0], proc.stderr
    assert (
        len(server.chat_requests) == 3
    )  # plan, step 1, step 2; step 3 never requested
    assert not (ws / "tests" / "test_notes.py").exists()
    assert (ws / "src" / "notes.py").exists() is False
