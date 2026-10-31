"""B-139: `ract -p` and a session turn treat the same scenario the same way.

The scenario is B-137's: the model goes straight to tools (a read_file call)
and then answers. Each pair below runs it through `ract -p` and through a
session turn (``session_turn.run_turn``, as the REPL calls it) on the fake
model server, and compares what each refused and which files changed. See
docs/design/B-139_headless_session_parity.md.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any


from ract.approval_callback import refuse_changes_callback
from ract.manager import Step
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from tests.fixtures.fake_model_server import Scenario
from tests.test_session_turn import _repo

SCENARIO = {
    "turns": [
        {
            "reply": {
                "kind": "tool_calls",
                "content": "I will read it first.",
                "calls": [{"name": "read_file", "arguments": {"path": "src/calc.py"}}],
            }
        },
        {"reply": {"kind": "text", "content": "add subtracts."}},
    ]
}


def _ws(tmp_path: Path, name: str, fake_model_server: Any) -> Path:
    server = fake_model_server(Scenario.from_dict(SCENARIO))
    (tmp_path / name).mkdir()
    ws = _repo(tmp_path / name, server.base_url)
    config = ws / "ract.yaml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\nagent:\n  step_tools: true\n",
        encoding="utf-8",
    )
    return ws


def _files(ws: Path) -> dict[str, bytes]:
    return {
        p.relative_to(ws).as_posix(): p.read_bytes()
        for p in ws.rglob("*")
        if p.is_file() and ".git" not in p.parts and ".ract" not in p.parts
    }


def _session_turn(ws: Path, monkeypatch, *, auto: bool, answers: list[str]):  # type: ignore[no-untyped-def]
    queue = list(answers)
    monkeypatch.setattr(
        "ract.approval_callback.read_line",
        lambda _p: queue.pop(0) if queue else "n",
    )
    stream = EventStream(session="s-parity")
    events: list[SessionEvent] = []
    stream.subscribe(events.append)
    code = run_turn(
        stream,
        TurnRequest(
            config=ws / "ract.yaml",
            intent="look at add",
            session_id="s-parity",
            resume=False,
            auto=auto,
            terminal=True,
        ),
        turn=1,
        cancel=threading.Event(),
    )
    return code, events


def test_nobody_to_ask_refuses_an_agent_step_even_past_plan_approval() -> None:
    # The defect: an agent step names no artifact and no tool call, and the
    # headless refusal let it through when plan approval was skipped (a replay).
    agent = Step(action="look", provider_hint="", expected_artifact="", agent=True)
    answer = Step(action="explain", provider_hint="", expected_artifact="")
    assert refuse_changes_callback(agent) is False
    assert refuse_changes_callback(answer) is True
