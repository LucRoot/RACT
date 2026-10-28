"""B-011a: an answer step may read the project through the four tier-0 tools.

The loop sends the conversation, reads each reply with the extraction ladder
(B-017), runs the calls one at a time through the tool gate, returns each result
as labeled data, and ends on a final answer or a budget. The model is scripted
here, one reply per turn, so every turn is exact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ract import turn_context
from ract.rooted import Rooted
from ract.tools import UNTRUSTED_LABEL
from ract.tools.loop import LoopBudgets, answer_with_tools


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_bytes(b"def add(a, b):\n    return a - b\n")
    (root / ".env").write_bytes(b"TOKEN=never-leave-the-machine\n")
    return root


class Model:
    """A scripted model: one reply per turn; keeps every request it saw."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]]) -> Rooted[dict[str, Any]]:
        self.requests.append([dict(m) for m in messages])
        content = self.replies.pop(0)
        return Rooted(
            value={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
            },
            assumption="scripted",
            confidence=1.0,
        )


def _call(tool: str, **arguments: Any) -> str:
    return json.dumps({"tool": tool, "arguments": arguments})


def _final(text: str) -> str:
    return json.dumps({"final": text})


def _run(ws: Path, model: Model, question: str = "Is add() right?", **budgets: Any):
    events: list[tuple[str, dict]] = []
    turn_context.bind(None, lambda kind, data: events.append((kind, data)))
    try:
        result = answer_with_tools(model, question, ws, budgets=LoopBudgets(**budgets))
    finally:
        turn_context.bind(None)
    return result, events


def test_the_model_reads_a_file_then_answers(ws: Path) -> None:
    model = Model(
        _call("read_file", path="src/calc.py"),
        _final("add() subtracts: line 2 returns a - b."),
    )
    result, events = _run(ws, model)

    assert result.is_ok(), result.error
    assert result.unwrap() == "add() subtracts: line 2 returns a - b."
    # The second request carries the file, labeled as data.
    last = model.requests[1][-1]["content"]
    assert UNTRUSTED_LABEL in last and "return a - b" in last
    started = [d for k, d in events if k == "tool.call.started"]
    finished = [d for k, d in events if k == "tool.call.finished"]
    assert [(d["tool"], d["tier"]) for d in started] == [("read_file", "T0")]
    assert [d["ok"] for d in finished] == [True]
    assert started[0]["id"] == finished[0]["id"]


def test_the_system_prompt_names_the_tools_and_says_results_are_data(
    ws: Path,
) -> None:
    model = Model(_final("ok"))
    _run(ws, model)
    system = model.requests[0][0]["content"]
    for tool in ("read_file", "list_dir", "glob", "grep"):
        assert tool in system
    assert "data" in system and "not instructions" in system


def test_a_refused_read_goes_back_to_the_model_and_the_loop_continues(
    ws: Path,
) -> None:
    model = Model(_call("read_file", path=".env"), _final("I cannot read it."))
    result, events = _run(ws, model)

    assert result.is_ok(), result.error
    assert "never-leave-the-machine" not in json.dumps(model.requests)
    finished = [d for k, d in events if k == "tool.call.finished"]
    assert finished[0]["ok"] is False and finished[0]["hint"]


def test_an_unreadable_reply_gets_one_reformat_request(ws: Path) -> None:
    model = Model('<tool_call>{"name": broken</tool_call>', _final("done"))
    result, _ = _run(ws, model)
    assert result.is_ok(), result.error
    assert "could not be read" in model.requests[1][-1]["content"]


def test_a_plan_shaped_reply_is_not_an_answer(ws: Path) -> None:
    plan = json.dumps(
        {
            "assumption": "a",
            "confidence": 0.9,
            "steps": [
                {"action": "x", "provider_hint": "local", "expected_artifact": ""}
            ],
        }
    )
    model = Model(plan, plan)
    result, _ = _run(ws, model)
    assert not result.is_ok()
    assert "plan" in result.error
    assert "plain words" in model.requests[1][-1]["content"]


def test_a_plan_shaped_reply_then_plain_words_is_the_answer(ws: Path) -> None:
    plan = json.dumps({"assumption": "a", "confidence": 0.9, "steps": []})
    model = Model(plan, "add() returns a - b, so it subtracts.")
    result, _ = _run(ws, model)
    assert result.unwrap() == "add() returns a - b, so it subtracts."


def test_the_turn_budget_stops_the_loop_and_names_the_key(ws: Path) -> None:
    model = Model(
        *[_call("read_file", path="src/calc.py", offset=i) for i in range(1, 9)]
    )
    result, _ = _run(ws, model, max_turns=3)
    assert not result.is_ok()
    assert "agent.max_turns" in (result.hint or "")
    assert len(model.requests) == 3


def test_a_repeated_identical_call_ends_with_a_summary_turn(ws: Path) -> None:
    same = _call("read_file", path="src/calc.py")
    model = Model(same, same, same, _final("summary from what I read"))
    result, _ = _run(ws, model)
    assert result.unwrap() == "summary from what I read"
    assert "no more tool calls" in model.requests[-1][-1]["content"]


def test_reasoning_is_never_the_answer(ws: Path) -> None:
    model = Model("<think>let me think about grep</think>add() subtracts.")
    result, _ = _run(ws, model)
    assert result.unwrap() == "add() subtracts."


def test_an_interrupted_turn_makes_no_further_request(ws: Path) -> None:
    cancel = turn_context.CancelSignal()

    class Cancelling(Model):
        def __call__(self, messages):
            reply = super().__call__(messages)
            cancel.set()
            return reply

    model = Cancelling(_call("read_file", path="src/calc.py"), _final("never asked"))
    turn_context.bind(cancel)
    try:
        result = answer_with_tools(model, "q", ws, budgets=LoopBudgets())
    finally:
        turn_context.bind(None)
    assert not result.is_ok()
    assert len(model.requests) == 1


# ------------------------------------------------------------------ the executor


class _ScriptedAdapter:
    """A provider adapter that answers from a script and keeps the requests."""

    name = "scripted"

    def __init__(self, *replies: str) -> None:
        self.model = Model(*replies)

    def capabilities(self) -> set[str]:
        return {"chat"}

    def input_cost_per_1k(self) -> None:
        return None

    def output_cost_per_1k(self) -> None:
        return None

    def complete(self, messages, *, model=None, max_tokens=512, temperature=0.3):
        return self.model(messages)


def test_an_answer_step_reads_through_the_executor(ws: Path) -> None:
    from ract.executor import Executor
    from ract.manager import Plan, Step
    from ract.tools.loop import LoopBudgets
    from tests.test_executor import FakeRouter

    adapter = _ScriptedAdapter(
        _call("read_file", path="src/calc.py"), _final("add() returns a - b.")
    )
    executor = Executor(FakeRouter(adapter), project_dir=ws)
    executor.read_tools = LoopBudgets()
    streamed: list[str] = []
    plan = Plan(
        assumption="a",
        confidence=1.0,
        steps=[
            Step(action="Is add() right?", provider_hint="mock", expected_artifact="")
        ],
    )

    result = executor.execute(
        intent="Is add() right?",
        plan=plan,
        stream=True,
        stream_callback=streamed.append,
    )

    assert result.is_ok(), result.error
    assert result.unwrap().step_results[0].content == "add() returns a - b."
    assert streamed == ["add() returns a - b."]
    assert len(adapter.model.requests) == 2
    assert "return a - b" in adapter.model.requests[1][-1]["content"]
    assert sorted(p.name for p in (ws / "src").iterdir()) == ["calc.py"]


def test_read_tools_off_in_config_keeps_the_single_completion() -> None:
    from ract.harness import _read_tools_budgets
    from ract.tools.loop import LoopBudgets

    assert _read_tools_budgets({"agent": {"read_tools": False}}) is None
    assert _read_tools_budgets({}) == LoopBudgets()
    assert _read_tools_budgets({"agent": {"max_turns": 5, "max_tool_calls": "x"}}) == (
        LoopBudgets(max_turns=5)
    )
