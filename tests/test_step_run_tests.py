"""B-112: the model calls run_tests inside a step; the operator's grant decides.

Real turns on the fake model server with ``agent.step_tools: true``; the
command is answered by the scripted runner (no command runs). Throwaway keys.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path
from typing import Any

import pytest

from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from ract.tools.command import ScriptedRunner
from tests.test_j4_named_test_runs import _grant
from tests.test_step_tools_wired import FIX_ARGS, _calls, _workspace


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "user-config"
    monkeypatch.setenv("APPDATA", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / ("python.exe" if os.name == "nt" else "python")
    exe.write_text("", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))


def _turn(ws: Path, monkeypatch, answers: list[str], runner) -> list[SessionEvent]:
    monkeypatch.setattr("ract.tools.command.default_runner", lambda: runner)
    queue = list(answers)
    monkeypatch.setattr(
        "ract.approval_callback.read_line",
        lambda _p: queue[0] if len(queue) == 1 else queue.pop(0),
    )
    stream = EventStream(session="s-steprun")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="make add add",
        session_id="s-steprun",
        resume=False,
        auto=True,
    )
    run_turn(stream, request, turn=1, cancel=threading.Event())
    return events


def _finished(events: list[SessionEvent], tool: str) -> list[dict[str, Any]]:
    started = {
        e.data["id"]
        for e in events
        if e.kind == "tool.call.started" and e.data["tool"] == tool
    }
    return [
        e.data
        for e in events
        if e.kind == "tool.call.finished" and e.data["id"] in started
    ]


def _scenario_ws(tmp_path, fake_model_server):
    return _workspace(
        tmp_path,
        fake_model_server,
        lambda digest: _calls(("edit_file", {**FIX_ARGS, "expected_digest": digest})),
        lambda _d: _calls(
            ("run_tests", {"selectors": ["tests/test_calc.py"], "reason": "check"})
        ),
    )


def test_with_a_grant_and_a_yes_the_step_runs_the_tests(
    tmp_path: Path, fake_model_server, monkeypatch, env
) -> None:
    ws = _scenario_ws(tmp_path, fake_model_server)
    _grant(ws)
    runner = ScriptedRunner([{"exit_code": 0, "stdout": "1 passed"}])
    # Answers: the tier-3 question during the step, then the review of its hunk.
    events = _turn(ws, monkeypatch, ["y", "a"], runner)
    finished = _finished(events, "run_tests")
    assert finished and finished[0]["ok"], finished
    assert runner.calls and runner.calls[0]["argv"][-1] == "tests/test_calc.py"
    # The step ran in its worktree, never in the operator's tree.
    assert Path(runner.calls[0]["cwd"]) != ws


def test_without_a_grant_the_call_is_refused_and_the_step_goes_on(
    tmp_path: Path, fake_model_server, monkeypatch, env
) -> None:
    ws = _scenario_ws(tmp_path, fake_model_server)
    runner = ScriptedRunner([{"exit_code": 0}])
    events = _turn(ws, monkeypatch, ["a", "y"], runner)
    finished = _finished(events, "run_tests")
    assert finished and not finished[0]["ok"]
    assert "ract policy init --guided" in finished[0]["hint"]
    assert runner.calls == []
    assert events[-1].data["outcome"] == "done"


def test_a_test_file_the_step_wrote_always_asks(
    tmp_path: Path, fake_model_server, monkeypatch, env
) -> None:
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda _d: _calls(
            (
                "write_file",
                {
                    "path": "tests/test_new.py",
                    "content": "def test_x():\n    pass\n",
                    "create": True,
                },
            ),
            ("run_tests", {"selectors": ["tests/test_new.py"]}),
        ),
    )
    _grant(ws)
    prompts: list[str] = []
    runner = ScriptedRunner([{"exit_code": 0}])
    monkeypatch.setattr("ract.tools.command.default_runner", lambda: runner)

    def read_line(prompt: str) -> str:
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("ract.approval_callback.read_line", read_line)
    stream = EventStream(session="s-written")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    run_turn(
        stream,
        TurnRequest(
            config=ws / "ract.yaml",
            intent="add a test",
            session_id="s-written",
            resume=False,
            auto=True,
        ),
        turn=1,
        cancel=threading.Event(),
    )
    assert "Run it once? [y/N]: " in prompts and runner.calls == []
    printed = json.dumps([e.data for e in events if e.kind == "notice"])
    assert "Traceback" not in printed
