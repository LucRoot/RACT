"""B-104 (D-104): ``ract run`` with no terminal refuses to change files unless ``--yolo``.

A script or CI job ran ``ract run`` and it changed files with no question and no
flag that said it may. Each case is a real ``ract run`` with stdin from NUL (not
a terminal) against the fake model server.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import _repo

WRITES = {
    "assumption": "add() is wrong",
    "confidence": 0.8,
    "steps": [
        {
            "action": "Fix add() in src/calc.py so it adds",
            "provider_hint": "local",
            "expected_artifact": "src/calc.py",
        }
    ],
}
ANSWERS = {
    "assumption": "a question",
    "confidence": 0.8,
    "steps": [
        {"action": "Explain add()", "provider_hint": "local", "expected_artifact": ""}
    ],
}
FIXED = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"


def _run(tmp_path: Path, fake_model_server: Any, plan: dict, *flags: str):
    turns = [{"reply": {"kind": "text", "content": json.dumps(plan)}}]
    turns += [{"reply": {"kind": "text", "content": FIXED}}]
    turns += [{"reply": {"kind": "text", "content": "Done."}}] * 3
    server = fake_model_server(Scenario.from_dict({"turns": turns}))
    ws = _repo(tmp_path, server.base_url)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "run",
            "fix add",
            "--config",
            "ract.yaml",
            *flags,
        ],
        cwd=ws,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )
    assert "Traceback" not in proc.stdout + proc.stderr
    return ws, proc


def test_a_change_is_refused_and_names_yolo(
    tmp_path: Path, fake_model_server: Any
) -> None:
    ws, proc = _run(tmp_path, fake_model_server, WRITES)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert "--yolo" in out and "has no terminal to ask" in out
    assert "return a - b" in (ws / "src" / "calc.py").read_text(encoding="utf-8")


def test_yolo_writes(tmp_path: Path, fake_model_server: Any) -> None:
    ws, proc = _run(tmp_path, fake_model_server, WRITES, "--yolo")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == FIXED


def test_an_answer_still_runs(tmp_path: Path, fake_model_server: Any) -> None:
    _, proc = _run(tmp_path, fake_model_server, ANSWERS)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_loop_without_yolo_is_refused(tmp_path: Path, fake_model_server: Any) -> None:
    _, proc = _run(tmp_path, fake_model_server, WRITES, "--loop")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3, out
    assert "--loop" in out and "--yolo" in out


def test_loop_with_yolo_runs_as_before(tmp_path: Path, fake_model_server: Any) -> None:
    _, proc = _run(tmp_path, fake_model_server, WRITES, "--loop", "--yolo")
    out = proc.stdout + proc.stderr
    # As before: the loop runs the project's tests, so an untrusted folder stops
    # at the trust question; it is not the --yolo refusal.
    assert "nothing can ask it yet" not in out
