"""B-112, J4: a request that names a failing test ends with that test run.

Real turns on the fake model server; the command is answered by the scripted
runner (no test runs a command), and a run counted as real is a stand-in
runner object that executes nothing either. Keys are throwaways.
"""

from __future__ import annotations

import os
import stat
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from ract.policy.grant import sign
from ract.policy.operator_key import generate, unlock
from ract.policy.verify import named_selectors
from ract.session_events import EventStream, SessionEvent
from ract.session_render import PlainRenderer
from ract.session_turn import TurnRequest, run_turn
from ract.tools.command import RawRun, ScriptedRunner
from tests.test_session_turn import _repo

PASS = "throwaway passphrase for a test"
INTENT = "tests/test_calc.py::test_add fails, fix it"


@pytest.fixture
def ws(tmp_path: Path, monkeypatch, fake_model_server) -> Path:
    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / ("python.exe" if os.name == "nt" else "python")
    exe.write_text("", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    server = fake_model_server("baseline_j4_today")
    return _repo(tmp_path, server.base_url)


def _grant(root: Path) -> None:
    key = generate(PASS)
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    (root / ".ract").mkdir(exist_ok=True)
    (root / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(root)}'\n"
        f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {now + timedelta(days=30):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\n"
        "sandbox: best_effort\n"
        "commands:\n  allow:\n    - id: tests\n      argv: [python, -m, pytest]\n",
        encoding="utf-8",
    )
    sign(root, unlock(PASS), key)


class StandIn:
    """A runner counted as real (name ``process``) that executes nothing."""

    name = "process"

    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code
        self.calls: list[list[str]] = []

    def run(self, argv, *, cwd, env, timeout_s):
        self.calls.append(list(argv))
        return RawRun(
            self.exit_code, b"1 passed" if self.exit_code == 0 else b"1 failed", b"", 7
        )


def _turn(ws: Path, monkeypatch, runner, answer: Any, auto: bool = True):
    monkeypatch.setattr("ract.tools.command.default_runner", lambda: runner)
    asked: list[str] = []

    # One answer for every question, or a list answered in order, the last repeated.
    answers = list(answer) if isinstance(answer, list) else [answer]

    def read_line(prompt: str) -> str:
        asked.append(prompt)
        now = answers[0] if len(answers) == 1 else answers.pop(0)
        if now is None:
            raise EOFError
        return now

    monkeypatch.setattr("ract.approval_callback.read_line", read_line)
    out: list[str] = []
    stream = EventStream(session="s-j4")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    stream.subscribe(PlainRenderer(out.append))
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent=INTENT,
        session_id="s-j4",
        resume=False,
        auto=auto,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    return code, events, "".join(out), asked


def test_the_named_test_runs_after_the_fix_and_verifies_the_turn(
    ws: Path, monkeypatch
) -> None:
    _grant(ws)
    runner = StandIn(0)
    code, events, text, asked = _turn(ws, monkeypatch, runner, "y")

    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    assert runner.calls and runner.calls[0][1:] == [
        "-m",
        "pytest",
        "--",
        "tests/test_calc.py::test_add",
    ]
    assert "Run it once? [y/N]: " in asked
    finished = events[-1].data
    assert finished["verification"]["status"] == "verified"
    assert finished["verdict"].endswith("the named test passed.")
    assert "verified: verified" in text and "not verified" not in text
    assert "ran: " in text and "tests/test_calc.py::test_add, exit 0" in text
    # Condition 4: the summary says where the command record lives.
    assert "command records are in the trace; they are not part of the signed Rootknot" in text


def test_a_failing_run_says_failed(ws: Path, monkeypatch) -> None:
    _grant(ws)
    code, events, _text, _asked = _turn(ws, monkeypatch, StandIn(1), "y")
    assert code == 0
    assert events[-1].data["verification"]["status"] == "failed"
    assert events[-1].data["verdict"].endswith("the named test failed.")


def test_a_no_runs_nothing_and_says_why(ws: Path, monkeypatch) -> None:
    _grant(ws)
    runner = StandIn(0)
    # Yes to the step, no to the command.
    code, events, text, _asked = _turn(ws, monkeypatch, runner, ["y", "n"])
    assert code == 0 and runner.calls == []
    verification = events[-1].data["verification"]
    assert verification["status"] == "not-run"
    assert "you declined the command" in verification["not_run_reason"]
    assert (
        text.strip().splitlines()[-1].strip().startswith("not verified: you declined")
    )


def test_without_a_terminal_nothing_runs(ws: Path, monkeypatch) -> None:
    _grant(ws)
    runner = StandIn(0)
    _code, events, _text, asked = _turn(ws, monkeypatch, runner, "y", auto=False)
    assert runner.calls == [] and "Run it once? [y/N]: " not in asked
    assert events[-1].data["verification"]["not_run_reason"] == (
        "nobody can answer the tier-3 question here"
    )


def test_the_scripted_runner_never_verifies(ws: Path, monkeypatch) -> None:
    _grant(ws)
    code, events, text, _asked = _turn(
        ws, monkeypatch, ScriptedRunner([{"exit_code": 0}]), "y"
    )
    assert code == 0
    verification = events[-1].data["verification"]
    assert verification["status"] == "not-run" and verification["fake_runs"] == 1
    assert "no command ran" in verification["not_run_reason"]
    assert "not verified: the scripted runner answered; no command ran" in text


def test_the_selectors_come_from_the_request() -> None:
    assert named_selectors(INTENT) == ["tests/test_calc.py::test_add"]
    assert named_selectors("fix tests/test_a.py and test_b.py") == [
        "tests/test_a.py",
        "test_b.py",
    ]
    assert named_selectors("the test fails") == []
