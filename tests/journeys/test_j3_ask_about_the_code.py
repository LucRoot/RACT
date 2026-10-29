"""J3 (UX_BAR): ask about the code, read-only.

The model searches and reads the file itself, the answer names the file it
read, and nothing is written. The run is a real `ract -p --ask` process
against the fake model server: the scripted model first asks for read_file on
src/calc.py, then answers from what it read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.fixtures.fake_model_server import FakeModelServer, Scenario
from tests.ux import run_baseline as rb

ANSWER = "add() is wrong: line 2 returns a - b, so it subtracts."


def _run(ws: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", *args],
        cwd=ws,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )


def test_the_answer_names_the_file_read_and_nothing_is_written(tmp_path: Path) -> None:
    scenario = Scenario.from_dict(
        {
            "turns": [
                {
                    "reply": {
                        "kind": "text",
                        "content": json.dumps(
                            {"tool": "read_file", "arguments": {"path": "src/calc.py"}}
                        ),
                    }
                },
                {"reply": {"kind": "text", "content": json.dumps({"final": ANSWER})}},
            ]
        }
    )
    with FakeModelServer(scenario) as server:
        ws = rb._workspace(tmp_path, "j3", git=True, files=rb.CALC_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        before = {
            p: p.read_bytes()
            for p in ws.rglob("*")
            if p.is_file() and ".git" not in p.parts
        }
        proc = _run(ws, ["-p", "--ask", "is add() correct?"])
        after = {
            p: p.read_bytes()
            for p in ws.rglob("*")
            if p.is_file() and ".git" not in p.parts
        }
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "Traceback" not in proc.stdout + proc.stderr
    assert ANSWER in proc.stdout
    assert len(server.chat_requests) == 2, (
        "one request for the read, one for the answer"
    )
    assert "return a - b" in json.dumps(server.chat_requests[1].body)
    assert after == before, "a read-only question changed a file"
