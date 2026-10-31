"""B-140: a malformed tool call is answered plainly, never reaches a tool, and three end the step.

The cases real models send: a wrong type, a missing field, an unknown tool,
arguments encoded twice as a JSON string, and three bad calls in a row. The
model is scripted one reply per turn (as in test_read_tools_loop); the last
test runs the same three bad calls through `ract -p --ask` on the fake server.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from ract import turn_context
from ract.rooted import Rooted
from ract.tool_calls import _decode_arguments
from ract.tools import loop
from ract.tools.loop import LoopBudgets, answer_with_tools
from tests.fixtures.fake_model_server import FakeModelServer, Scenario
from tests.ux import run_baseline as rb


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_bytes(b"def add(a, b):\n    return a - b\n")
    return root


class Model:
    """One reply per turn: a text reply, or a native tool_calls message."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.requests: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]]) -> Rooted[dict[str, Any]]:
        self.requests.append([dict(m) for m in messages])
        reply = self.replies.pop(0)
        message = reply if isinstance(reply, dict) else {"content": reply}
        return Rooted(
            value={"choices": [{"message": message, "finish_reason": "stop"}]},
            assumption="scripted",
            confidence=1.0,
        )


def _call(tool: str, **arguments: Any) -> str:
    return json.dumps({"tool": tool, "arguments": arguments})


def _final(text: str) -> str:
    return json.dumps({"final": text})


@pytest.fixture
def ran(monkeypatch) -> list[str]:
    """The calls that reached the gate (``_run_call``)."""
    seen: list[str] = []
    real = loop._run_call

    def counting(gate, call, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(call.name)
        return real(gate, call, *args, **kwargs)

    monkeypatch.setattr(loop, "_run_call", counting)
    return seen


def _run(ws: Path, model: Model):  # type: ignore[no-untyped-def]
    events: list[tuple[str, dict]] = []
    turn_context.bind(None, lambda kind, data: events.append((kind, data)))
    try:
        result = answer_with_tools(model, "Is add() right?", ws, budgets=LoopBudgets())
    finally:
        turn_context.bind(None)
    return result, events


def _told(model: Model, turn: int) -> str:
    """What the loop said to the model before its reply number *turn*."""
    return str(model.requests[turn][-1]["content"])


def test_a_wrong_type_is_named_with_the_shape_and_the_model_goes_on(
    ws: Path, ran: list[str]
) -> None:
    model = Model(
        _call("read_file", path=5), _call("read_file", path="src/calc.py"), _final("ok")
    )
    result, _ = _run(ws, model)
    assert result.is_ok(), result.error
    told = _told(model, 1)
    assert "read_file arguments refused: path:" in told
    assert "read_file takes {path: string" in told
    assert ran == ["read_file"]  # the malformed call never reached the gate


def test_a_missing_field_is_named(ws: Path, ran: list[str]) -> None:
    model = Model(_call("read_file"), _final("ok"))
    result, _ = _run(ws, model)
    assert result.is_ok()
    assert "path: Field required" in _told(model, 1)
    assert ran == []


def test_an_unknown_tool_lists_only_the_offered_tools(ws: Path, ran: list[str]) -> None:
    model = Model(_call("delete_everything", path="."), _final("ok"))
    result, _ = _run(ws, model)
    assert result.is_ok()
    told = _told(model, 1)
    assert "no tool named 'delete_everything'" in told
    assert "read_file" in told and "write_file" not in told  # read loop: reads only
    assert ran == []


def test_arguments_encoded_twice_are_decoded_once(ws: Path, ran: list[str]) -> None:
    twice = json.dumps(json.dumps({"path": "src/calc.py"}))
    native = {
        "content": "",
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "read_file", "arguments": twice},
            }
        ],
    }
    model = Model(native, _final("add() subtracts"))
    result, _ = _run(ws, model)
    assert result.is_ok(), result.error
    assert ran == ["read_file"]
    assert "return a - b" in json.dumps(model.requests[1])
    # Only once: three levels are still refused.
    thrice = json.dumps(twice)
    assert _decode_arguments(thrice)[0] is None


def test_three_bad_calls_end_the_step_and_none_reaches_a_tool(
    ws: Path, ran: list[str]
) -> None:
    model = Model(
        _call("read_file", path=5),
        _call("nope"),
        _call("read_file"),
        _final("never asked"),
    )
    result, _ = _run(ws, model)
    assert not result.is_ok()
    assert result.error.startswith("The model did not produce a valid tool call")
    assert ran == []
    assert len(model.requests) == 3  # no fourth request after the cap


def test_the_turn_says_so_through_ract_p(tmp_path: Path) -> None:
    bad = [{"reply": {"kind": "text", "content": _call("nope")}} for _ in range(3)]
    with FakeModelServer(Scenario.from_dict({"turns": bad})) as server:
        ws = rb._workspace(tmp_path, "b140", git=True, files=rb.CALC_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
        proc = subprocess.run(
            [sys.executable, "-m", "ract.cli", "--config", "ract.yaml"]
            + ["-p", "--ask", "is add() correct?"],
            cwd=ws,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            stdin=subprocess.DEVNULL,
        )
    assert proc.returncode != 0
    assert "did not produce a valid tool call" in proc.stdout + proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
