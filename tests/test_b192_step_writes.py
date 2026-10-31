"""B-192 (G-288): the writes a step's tools make count for the verifier.

Real turns on the fake model server with ``agent.step_tools: true``. The
commands are answered by a scripted runner that reports itself as a process
runner, so the verifier counts its runs; no command runs. Throwaway keys.

- A tool write after a passing ``run_tests`` makes the turn ``stale``.
- A passing ``run_tests`` after the last tool write is ``verified``: the apply
  that brings the worktree's files to the operator is not a second change.
- A test run that collects nothing (pytest's exit 5) makes the turn ``no-tests``.
- The headless ``ract.result/1`` carries the same status.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ract import headless
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from ract.tools.command import ScriptedRunner
from tests.test_j4_named_test_runs import _grant
from tests.test_step_run_tests import env  # noqa: F401  (fixture)
from tests.test_step_tools_wired import FIX_ARGS, _calls, _workspace

RUN = ("run_tests", {"selectors": ["tests/test_calc.py"], "reason": "check"})
PASSED = {"exit_code": 0, "stdout": "1 passed in 0.01s"}
NO_TESTS = {"exit_code": 5, "stdout": "no tests ran in 0.01s"}


class _CountedRunner(ScriptedRunner):
    """Scripted, but its runs count for the verifier as a real runner's would."""

    name = "process"


def _edit(digest: str) -> dict[str, Any]:
    return {**FIX_ARGS, "expected_digest": digest}


def _turn(ws: Path, monkeypatch, script: list[dict[str, Any]]) -> list[SessionEvent]:
    _grant(ws)
    runner = _CountedRunner(script)
    monkeypatch.setattr("ract.tools.command.default_runner", lambda rule=None: runner)
    # Every question is answered yes: the tier-3 run, then the review of hunks.
    monkeypatch.setattr("ract.approval_callback.read_line", lambda _p: "y")
    stream = EventStream(session="s-b192")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="make add add",
        session_id="s-b192",
        resume=False,
        auto=True,
    )
    run_turn(stream, request, turn=1, cancel=threading.Event())
    assert runner.calls, "the step did not run its tests"
    return events


def _status(events: list[SessionEvent]) -> str:
    return events[-1].data["verification"]["status"]


def test_a_tool_write_then_a_passing_run_is_verified(
    tmp_path: Path, fake_model_server, monkeypatch, env  # noqa: F811
) -> None:
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda digest: _calls(("edit_file", _edit(digest))),
        lambda _d: _calls(RUN),
    )
    events = _turn(ws, monkeypatch, [PASSED])
    assert events[-1].data["changed"] == ["src/calc.py"]
    assert _status(events) == "verified"


def test_a_tool_write_after_a_passing_run_is_stale(
    tmp_path: Path, fake_model_server, monkeypatch, env  # noqa: F811
) -> None:
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda _d: _calls(RUN),
        lambda digest: _calls(("edit_file", _edit(digest))),
    )
    events = _turn(ws, monkeypatch, [PASSED])
    assert _status(events) == "stale"


def test_a_new_file_written_after_the_run_is_stale(
    tmp_path: Path, fake_model_server, monkeypatch, env  # noqa: F811
) -> None:
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda digest: _calls(("edit_file", _edit(digest))),
        lambda _d: _calls(RUN),
        lambda _d: _calls(
            (
                "write_file",
                {"path": "src/extra.py", "content": "X = 1\n", "create": True},
            )
        ),
    )
    events = _turn(ws, monkeypatch, [PASSED])
    assert _status(events) == "stale"


def test_a_run_that_collects_no_tests_is_no_tests(
    tmp_path: Path, fake_model_server, monkeypatch, env  # noqa: F811
) -> None:
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda digest: _calls(("edit_file", _edit(digest))),
        lambda _d: _calls(RUN),
    )
    events = _turn(ws, monkeypatch, [NO_TESTS])
    assert _status(events) == "no-tests"


def test_the_headless_result_carries_stale(
    tmp_path: Path, fake_model_server, monkeypatch, env  # noqa: F811
) -> None:
    # `ract -p` runs this same turn (headless._run calls run_turn) and builds
    # ract.result/1 from its events.
    ws = _workspace(
        tmp_path,
        fake_model_server,
        lambda _d: _calls(RUN),
        lambda digest: _calls(("edit_file", _edit(digest))),
    )
    events = _turn(ws, monkeypatch, [PASSED])
    result = headless.result_object(events, session="s-b192", exit_code=0)
    assert result["schema"] == "ract.result/1"
    assert result["verification"]["status"] == "stale"
