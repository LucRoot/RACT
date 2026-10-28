"""J10 (UX_BAR): failure paths.

Provider down, a missing key variable and a garbage reply each give a cause,
leave the workspace as it was, and print a next action. No traceback reaches
the user, and escape sequences in a reply reach the screen harmless.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.fake_model_server import FakeModelServer, Scenario
from tests.ux import run_baseline as rb

CLOSED_PORT = "http://127.0.0.1:9/v1"
MISSING_KEY = "RACT_B074_MISSING_KEY"


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


def _output(proc: subprocess.CompletedProcess[str]) -> str:
    return proc.stdout + proc.stderr


def _assert_clean_failure(proc: subprocess.CompletedProcess[str], ws: Path) -> None:
    assert proc.returncode != 0
    assert "Traceback" not in _output(proc)
    assert "hint:" in _output(proc), "a failure must name a next action"
    # Read as text: line endings written on Windows do not matter here.
    calc = (ws / "src" / "calc.py").read_text(encoding="utf-8")
    assert calc == rb.CALC_FILES["src/calc.py"]


def test_provider_down_gives_a_cause_and_a_next_action(tmp_path: Path) -> None:
    ws = rb._workspace(tmp_path, "down", git=True, files=rb.CALC_FILES)
    rb._configure(ws, CLOSED_PORT, "nothing-listening")
    proc = _run(ws, ["-p", "fix add", "--output-format", "text"])
    _assert_clean_failure(proc, ws)
    assert "nothing is answering at" in _output(proc)


@pytest.mark.xfail(
    strict=True,
    reason="B-074 FOUND: a missing key variable is not named; the run sends the request anyway and the step fails with no cause (S2, key handling: BUILDER)",
)
def test_a_missing_key_variable_is_named(tmp_path: Path) -> None:
    with FakeModelServer("plan_three_steps") as server:
        ws = rb._workspace(tmp_path, "nokey", git=True, files=rb.CALC_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        config = (ws / "ract.yaml").read_text(encoding="utf-8")
        assert "    model: fake-coder\n" in config
        config = config.replace(
            "    model: fake-coder\n",
            f"    model: fake-coder\n    api_key: ${{{MISSING_KEY}}}\n",
        )
        (ws / "ract.yaml").write_text(config, encoding="utf-8")
        proc = _run(ws, ["-p", "fix add", "--output-format", "text"])
    _assert_clean_failure(proc, ws)
    assert MISSING_KEY in _output(proc)


def test_a_garbage_reply_with_escape_sequences_reaches_the_screen_harmless(
    tmp_path: Path,
) -> None:
    garbage = "\x1b[2J\x1b]0;pwned\x07\x1b[31mred text\x1b[0m\rover\x08\x08done\n"
    scenario = Scenario.from_dict(
        {"turns": [{"reply": {"kind": "text", "content": garbage}}]}
    )
    with FakeModelServer(scenario) as server:
        ws = rb._workspace(tmp_path, "garbage", git=True, files=rb.CALC_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        proc = _run(ws, ["-p", "where is add?", "--output-format", "text"])
    text = _output(proc)
    assert "Traceback" not in text
    assert "\x1b[2J" not in text and "\x1b]0;" not in text
    assert "\x07" not in text and "\x08" not in text
