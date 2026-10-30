"""B-110 D5: the step agent loop writes in the step's worktree, through the tier gate.

The model is scripted, one reply per turn. The root is a temporary project
standing in for the step worktree; nothing here touches a live tree or runs
a command.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from ract import turn_context
from ract.rooted import Rooted
from ract.tools.loop import (
    LoopBudgets,
    StepWork,
    answer_with_tools,
    work_with_tools,
)

CALC = b"def add(a, b):\n    return a - b\n"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_bytes(CALC)
    return root


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Model:
    """A scripted model: one reply per turn, with an optional usage block."""

    def __init__(self, *replies: str, usage: int | None = None) -> None:
        self.replies = list(replies)
        self.usage = usage
        self.requests: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]]) -> Rooted[dict[str, Any]]:
        self.requests.append([dict(m) for m in messages])
        raw: dict[str, Any] = {
            "choices": [
                {"message": {"content": self.replies.pop(0)}, "finish_reason": "stop"}
            ]
        }
        if self.usage is not None:
            raw["usage"] = {"total_tokens": self.usage}
        return Rooted(value=raw, assumption="scripted", confidence=1.0)


def _call(tool: str, **arguments: Any) -> dict[str, Any]:
    return {"tool": tool, "arguments": arguments}


def _reply(*calls: dict[str, Any]) -> str:
    return json.dumps(calls[0] if len(calls) == 1 else list(calls))


def _final(text: str) -> str:
    return json.dumps({"final": text})


def _fix() -> dict[str, Any]:
    return _call(
        "edit_file",
        path="src/calc.py",
        old="a - b",
        new="a + b",
        expected_digest=_sha(CALC),
    )


def _work(ws: Path, model: Model, approve=None, **budgets: Any):
    events: list[tuple[str, dict]] = []
    work = StepWork()
    turn_context.bind(None, lambda kind, data: events.append((kind, data)))
    try:
        result = work_with_tools(
            model,
            "Make add() add.",
            ws,
            budgets=LoopBudgets(**budgets),
            approve_tier_2=approve,
            work=work,
        )
    finally:
        turn_context.bind(None)
    return result, work, events


def test_the_step_reads_edits_and_reports_its_change(ws: Path) -> None:
    model = Model(
        _reply(_call("read_file", path="src/calc.py")),
        _reply(_fix()),
        _final("add() now returns a + b."),
    )
    result, work, _events = _work(ws, model)

    assert result.is_ok(), result.error
    done = result.unwrap()
    assert done.summary == "add() now returns a + b."
    assert (ws / "src" / "calc.py").read_bytes() == CALC.replace(b"a - b", b"a + b")
    assert [c["tool"] for c in done.changes] == ["edit_file"]
    assert done.changes[0]["path"] == "src/calc.py"
    assert done.changes[0]["digest_before"] == _sha(CALC)
    assert done.tool_calls == 2 and done.turns == 3
    # The system prompt offers the write tools and says results are data.
    system = model.requests[0][0]["content"]
    assert "edit_file(" in system and "not instructions" in system


def test_a_tier_2_write_is_refused_without_the_operators_answer(ws: Path) -> None:
    workflow = _call(
        "write_file",
        path=".github/workflows/ci.yml",
        content="on: push\n",
        create=True,
    )
    model = Model(_reply(workflow), _final("Added a workflow; approved."))
    result, work, _events = _work(ws, model)

    # The model's own words never approve: the file is not written.
    assert not (ws / ".github" / "workflows" / "ci.yml").exists()
    assert work.changes == []
    refused = model.requests[1][-1]["content"]
    assert 'status="refused"' in refused and "tier 2" in refused
    assert result.is_ok()  # the step ends; the harness judges what changed


def test_a_tier_2_write_runs_on_the_operators_yes(ws: Path) -> None:
    asked: list[str] = []

    def operator(name: str, args: Any) -> bool:
        asked.append(name)
        return True

    workflow = _call(
        "write_file", path=".github/workflows/ci.yml", content="on: push\n", create=True
    )
    model = Model(_reply(workflow), _final("Added a workflow."))
    result, work, _events = _work(ws, model, approve=operator)

    assert result.is_ok(), result.error
    assert asked == ["write_file"]
    assert (ws / ".github" / "workflows" / "ci.yml").read_text() == "on: push\n"
    assert work.changes[0]["tier"] == "T2"


def test_a_failed_call_stops_the_rest_of_its_turn(ws: Path) -> None:
    # Call one writes, call two fails (wrong digest), call three must not run.
    model = Model(
        _reply(
            _call("write_file", path="notes.txt", content="one\n", create=True),
            _call("delete_file", path="src/calc.py", expected_digest="0" * 64),
            _call("write_file", path="later.txt", content="three\n", create=True),
        ),
        _final("Done."),
    )
    result, work, _events = _work(ws, model)

    assert result.is_ok(), result.error
    assert (ws / "notes.txt").read_text() == "one\n"  # call one's effect stays
    assert (ws / "src" / "calc.py").read_bytes() == CALC  # call two changed nothing
    assert not (ws / "later.txt").exists()  # call three never ran
    follow = model.requests[1][-1]["content"]
    assert "not run: an earlier call in this reply failed" in follow
    assert [c["path"] for c in work.changes] == ["notes.txt"]


def test_the_token_budget_stops_the_step_and_keeps_what_was_written(
    ws: Path,
) -> None:
    model = Model(
        _reply(_fix()), _reply(_call("read_file", path="src/calc.py")), usage=600
    )
    result, work, _events = _work(ws, model, max_tokens_per_step=1000)

    assert not result.is_ok()
    assert "agent.max_tokens_per_step" in (result.hint or "")
    assert "1200" in (result.error or "")
    assert len(model.requests) == 2  # no third request after the budget
    # The edit stays in the worktree and is reported; nothing applies it here.
    assert [c["tool"] for c in work.changes] == ["edit_file"]
    assert work.tokens == 1200


def test_the_turn_and_call_budgets_name_their_keys(ws: Path) -> None:
    looping = Model(*[_reply(_call("list_dir", path="src")) for _ in range(2)])
    turns, _work_done, _ = _work(ws, looping, max_turns=1)
    assert not turns.is_ok() and "agent.max_turns" in (turns.hint or "")

    calls = Model(
        _reply(_call("read_file", path="src/calc.py"), _call("list_dir", path="src")),
        _final("done"),
    )
    capped, _w, _ = _work(ws, calls, max_tool_calls=1)
    follow = calls.requests[1][-1]["content"]
    assert 'status="refused"' in follow  # the second call met the call budget
    assert capped.is_ok()


def test_an_interrupted_step_makes_no_further_request(ws: Path) -> None:
    model = Model(_reply(_fix()), _final("never sent"))
    cancel = turn_context.CancelSignal()
    cancel.set()
    turn_context.bind(cancel)
    try:
        result = work_with_tools(model, "Make add() add.", ws)
    finally:
        turn_context.bind(None)
    assert not result.is_ok() and result.hint == "interrupted"
    assert model.requests == []
    assert (ws / "src" / "calc.py").read_bytes() == CALC


def test_a_plan_shaped_summary_still_ends_the_step(ws: Path) -> None:
    # The verdict is the harness's (T1), so the step loop takes any summary.
    model = Model(_reply(_fix()), json.dumps({"final": json.dumps({"steps": []})}))
    result, _work_done, _ = _work(ws, model)
    assert result.is_ok(), result.error


def test_the_answer_loop_still_offers_no_write_tool(ws: Path) -> None:
    model = Model(_reply(_fix()), _final("I could not change it."))
    answer_with_tools(model, "Fix add().", ws)
    # Unknown to the answer loop, the call is never run, however it ends.
    assert "edit_file(" not in model.requests[0][0]["content"]
    assert (ws / "src" / "calc.py").read_bytes() == CALC


def test_the_token_budget_comes_from_ract_yaml_only_when_positive() -> None:
    from ract.harness import _read_tools_budgets

    assert _read_tools_budgets({}).max_tokens_per_step is None
    budgets = _read_tools_budgets({"agent": {"max_tokens_per_step": 50000}})
    assert budgets.max_tokens_per_step == 50000
    for bad in (0, -5, "lots", True):
        assert (
            _read_tools_budgets(
                {"agent": {"max_tokens_per_step": bad}}
            ).max_tokens_per_step
            is None
        )
