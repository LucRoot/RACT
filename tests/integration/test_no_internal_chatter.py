"""UX-21: a normal run does not print maintainer diagnostics.

Every run printed "sandbox_env: scrubbed N environment variable(s) ..." to
stderr: a WARNING-level log line reaching the terminal through Python's
last-resort handler. UX_BAR: internal chatter goes to the log, not the
user's terminal.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.ux import run_baseline as rb


def test_run_does_not_print_sandbox_scrub_summary(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = rb._workspace(tmp_path, "ws", git=True, files=rb.CALC_FILES)
    rb._configure(ws, server.base_url, "fake-coder")
    for args in (
        ["add", "-A"],
        [
            "-c",
            "user.name=d",
            "-c",
            "user.email=d@example.invalid",
            "commit",
            "-q",
            "-m",
            "c",
        ],
    ):
        subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["OPENAI_API_KEY"] = "sk-test-not-real"  # guarantees something is scrubbed

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "--config",
            "ract.yaml",
            "--yolo",
            "tests/test_calc.py::test_add fails, fix it",
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
    assert "sandbox_env:" not in result.stderr
    assert "sandbox_env:" not in result.stdout
