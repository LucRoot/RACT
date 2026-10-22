"""The turn context across threads, and the abandoned worker (G-026, G-027).

The turn's cancel signal, event reporter and written-paths list live in
ContextVars, so pool threads that are submitted through run_with_ambient
see them. After Ctrl-C the worker may still be blocked in a model call;
when that call returns, during the next turn or at idle, nothing from it
may reach the stream, the working tree, the step branches or the history.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from ract import turn_context
from ract.runtime import run_with_ambient
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import FIXED, _repo


def _wait_until(condition: Callable[[], bool], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached in time")
        time.sleep(0.01)


def _stream() -> tuple[EventStream, list[SessionEvent]]:
    stream = EventStream(session="s-ctx")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    return stream, events


# ---------------------------------------------------------------- pool threads


def test_a_pool_thread_reports_into_the_turn_in_order() -> None:
    stream, events = _stream()
    stream.emit("turn.started", {"input": "x", "queued": False}, turn=1)
    turn_context.bind(
        threading.Event(), lambda kind, data: stream.emit(kind, data, turn=1)
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.submit(
                run_with_ambient(
                    turn_context.report,
                    "step.started",
                    {"n": 1, "action": "a", "target": None},
                )
            ).result(timeout=10)
    finally:
        turn_context.bind(None)
    assert [(e.seq, e.kind, e.turn) for e in events] == [
        (1, "turn.started", 1),
        (2, "step.started", 1),
    ]


def test_a_cancel_set_on_the_turn_is_seen_inside_a_pool_thread() -> None:
    cancel = threading.Event()
    turn_context.bind(cancel)
    try:
        cancel.set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            seen = pool.submit(run_with_ambient(turn_context.cancelled)).result(10)
            # A bare submit runs in the pool thread's own, empty context;
            # that is why work is submitted through run_with_ambient.
            bare = pool.submit(turn_context.cancelled).result(10)
    finally:
        turn_context.bind(None)
    assert seen is True
    assert bare is False


def test_recorded_paths_are_relative_and_suspended_inside_a_worktree(
    tmp_path: Path,
) -> None:
    written: list[str] = []
    turn_context.bind(threading.Event(), written=written)
    try:
        turn_context.record_written(tmp_path, [tmp_path / "src" / "a.py", "b.txt"])
        with turn_context.recording_suspended():
            turn_context.record_written(tmp_path, ["worktree-only.py"])
        turn_context.record_written(tmp_path, ["b.txt"])
    finally:
        turn_context.bind(None)
    assert written == ["src/a.py", "b.txt"]


def test_changes_ract_did_not_write_are_reported(
    tmp_path: Path, fake_model_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    import ract.ract_runner as runner

    real = runner.run_ract

    def run_and_touch(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        (ws / "README.md").write_text("edited in another shell\n", encoding="utf-8")
        return result

    monkeypatch.setattr(runner, "run_ract", run_and_touch)
    stream, events = _stream()

    run_turn(
        stream,
        TurnRequest(
            config=ws / "ract.yaml", intent="fix add", session_id=None, resume=False
        ),
        turn=1,
        cancel=threading.Event(),
    )

    assert events[-1].data["changed"] == ["src/calc.py"]  # what RACT wrote
    notices = [e.data["text"] for e in events if e.kind == "notice"]
    assert any("RACT did not write: README.md" in n for n in notices)


# ---------------------------------------------------------------- G-027


@pytest.mark.parametrize("release_at", ["during_next_turn", "idle"])
def test_a_late_reply_from_an_interrupted_turn_leaves_no_trace(
    tmp_path: Path, fake_model_server: Any, release_at: str
) -> None:
    def plan(target: str) -> str:
        return json.dumps(
            {
                "assumption": "a",
                "confidence": 0.9,
                "steps": [
                    {
                        "action": f"Write {target}",
                        "provider_hint": "local",
                        "expected_artifact": target,
                    }
                ],
            }
        )

    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    # Turn 1's plan arrives only when the test releases it.
                    {
                        "reply": {
                            "kind": "text",
                            "content": plan("src/calc.py"),
                            "wait_for": "first",
                        }
                    },
                    {"reply": {"kind": "text", "content": plan("README.md")}},
                    {"reply": {"kind": "text", "content": "# calc\n\nturn two\n"}},
                    # Anything turn 1 asks for after the release would get this.
                    {"reply": {"kind": "text", "content": FIXED}, "repeat": True},
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)
    calc_before = (ws / "src" / "calc.py").read_text(encoding="utf-8")
    stream, events = _stream()
    codes: dict[int, int] = {}

    def turn(n: int, intent: str, cancel: threading.Event) -> None:
        codes[n] = run_turn(
            stream,
            TurnRequest(
                config=ws / "ract.yaml",
                intent=intent,
                session_id="s-g027",
                resume=False,
            ),
            turn=n,
            cancel=cancel,
        )

    cancel_1 = threading.Event()
    first = threading.Thread(target=turn, args=(1, "fix calc", cancel_1))
    first.start()
    _wait_until(lambda: len(server.chat_requests) >= 1)  # turn 1 is in the model call
    cancel_1.set()  # Ctrl-C; the session returns to the prompt
    mark = len(events)

    second = threading.Thread(
        target=turn, args=(2, "update the readme", threading.Event())
    )
    second.start()
    if release_at == "during_next_turn":
        _wait_until(any_event(events, "plan.proposed", turn=2))
        server.release("first")
        second.join(60)
    else:
        second.join(60)
        server.release("first")  # the session is idle at the prompt
    first.join(60)
    assert not first.is_alive() and not second.is_alive()

    assert codes == {1: 5, 2: 0}
    # (a) nothing from turn 1 after the interrupt, and no cost entries
    later = events[mark:]
    assert all(e.turn == 2 for e in later), [(e.kind, e.turn) for e in later]
    assert not any(e.kind == "cost.updated" for e in events)
    # (b) turn 1 applied nothing and made no step branch
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == calc_before
    assert "turn two" in (ws / "README.md").read_text(encoding="utf-8")
    branches = subprocess.run(
        ["git", "branch", "--list", "rootact/step/*"],
        cwd=ws,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert len(branches) == 1
    # (c) the history holds only turn 2
    state = json.loads(
        (ws / ".ract" / "sessions" / "s-g027.json").read_text(encoding="utf-8")
    )
    assert state["intent"].endswith("update the readme")
    assert "fix calc" not in json.dumps(state)


def any_event(
    events: list[SessionEvent], kind: str, *, turn: int
) -> Callable[[], bool]:
    return lambda: any(e.kind == kind and e.turn == turn for e in list(events))


def test_the_turn_context_reaches_the_loop_controller_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G-028: loop iterations run in a ThreadPoolExecutor worker
    (LoopController._run_with_timeout); events and cancel must reach it."""
    import ract.loop_controller as lc
    from ract.rooted import Rooted

    seen: dict[str, Any] = {}

    def fake_run_ract(*args: Any, **kwargs: Any) -> Rooted[Any]:
        turn_context.report("step.started", {"n": 1, "action": "a", "target": None})
        seen["cancelled_before"] = turn_context.cancelled()
        cancel.set()
        seen["cancelled_after"] = turn_context.cancelled()
        seen["thread"] = threading.current_thread().name
        return Rooted(value=None, assumption="a", confidence=0.0, error="stub")

    monkeypatch.setattr(lc, "run_ract", fake_run_ract)
    controller = object.__new__(lc.LoopController)
    controller.config_path = tmp_path / "ract.yaml"
    controller.allow_load_bearing_override = False
    controller.allow_novelty_overrun = False
    controller.iteration_timeout = 30
    reported: list[str] = []
    cancel = threading.Event()
    turn_context.bind(cancel, lambda kind, data: reported.append(kind))
    try:
        controller._run_with_timeout("intent")
    finally:
        turn_context.bind(None)

    assert seen["thread"] != threading.current_thread().name  # really a pool thread
    assert reported == ["step.started"]
    assert seen == {
        "cancelled_before": False,
        "cancelled_after": True,
        "thread": seen["thread"],
    }
