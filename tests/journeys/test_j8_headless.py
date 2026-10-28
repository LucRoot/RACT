"""J8 (UX_BAR): headless use in CI.

`ract -p "..." --output-format json` returns the documented result object
(`ract.result/1`), exit 0 on a successful answer, a non-zero code when a
change is refused, and it reads its question from stdin when there is one.
The model is the fake model server; the process is the real `ract`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.fixtures.fake_model_server import FakeModelServer
from tests.ux import run_baseline as rb

SCHEMA = "ract.result/1"
RESULT_KEYS = {
    "schema",
    "outcome",
    "exit_code",
    "session",
    "turns",
    "verdict",
    "final_text",
    "changed",
    "verification",
    "provenance",
    "cost",
}


def _run(
    ws: Path, args: list[str], stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "--config", "ract.yaml", *args],
        cwd=ws,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )


def _result(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(proc.stdout)


def test_an_answer_returns_the_documented_result_object(tmp_path: Path) -> None:
    with FakeModelServer("baseline_j3_today") as server:
        ws = rb._workspace(tmp_path, "answer", git=True, files=rb.APP_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        proc = _run(
            ws, ["-p", "where is the config loader?", "--output-format", "json"]
        )
    assert proc.returncode == 0, proc.stderr[-400:]
    result = _result(proc)
    assert set(result) >= RESULT_KEYS
    assert result["schema"] == SCHEMA
    assert result["exit_code"] == 0
    assert result["final_text"].strip() != ""


def test_a_refused_change_exits_non_zero_and_writes_nothing(tmp_path: Path) -> None:
    with FakeModelServer("plan_three_steps") as server:
        ws = rb._workspace(tmp_path, "refused", git=True, files=rb.CALC_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        before = (ws / "src" / "calc.py").read_bytes()
        proc = _run(ws, ["-p", "fix add", "--output-format", "json"])
    assert proc.returncode != 0, "a refused change must not exit 0"
    result = _result(proc)
    assert result["exit_code"] == proc.returncode
    assert (ws / "src" / "calc.py").read_bytes() == before
    assert not (ws / "src" / "notes.py").exists()


def test_the_question_can_come_from_stdin(tmp_path: Path) -> None:
    with FakeModelServer("baseline_j3_today") as server:
        ws = rb._workspace(tmp_path, "stdin", git=True, files=rb.APP_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        proc = _run(
            ws, ["-p", "--output-format", "json"], stdin="where is the config loader?\n"
        )
    assert proc.returncode == 0, proc.stderr[-400:]
    assert _result(proc)["schema"] == SCHEMA
