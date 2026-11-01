"""B-177 wiring: the ``todo`` tool reaches the step loop, the harness applies its facts, ``/todo`` shows the list.

MASON's first slice built the list, the tool (returning facts, writing nothing)
and the view. The wiring registers the tool for the step agent loop only (the
read-only answer loop has no list to apply facts to), applies the facts after
each step to the workspace's to-do list (``.ract/todo.json``), and gives the
REPL a ``/todo`` command.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract.todo_list import TodoList, load as load_todo
from ract.todo_list import apply_todo_facts, apply_step_todo_facts
from ract.tools import REGISTRY
from ract.tools.loop import StepWork, answer_tools, work_tools


def test_the_todo_tool_is_offered_to_the_step_loop_only() -> None:
    assert "todo" in REGISTRY
    assert "todo" in work_tools()
    # The read-only answer loop has no list to apply the facts to (MASON's
    # 00:57 decision), so it does not offer the tool.
    assert "todo" not in answer_tools()


def test_a_step_todo_fact_is_applied_and_saved(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    notes = apply_step_todo_facts(
        project, [{"tool": "todo", "todo_op": {"op": "add", "text": "fix the adder"}}]
    )
    assert notes == ["added item 1"]
    saved = load_todo(project / ".ract")
    assert [item.text for item in saved.items] == ["fix the adder"]
    # A second step claims it done: the claim is shown, the item stays open.
    notes = apply_step_todo_facts(
        project,
        [{"tool": "todo", "todo_op": {"op": "claim_done", "id": 1}}],
    )
    saved = load_todo(project / ".ract")
    assert saved.items[0].model_claim is True
    assert saved.items[0].state == "open"
    assert json.loads((project / ".ract" / "todo.json").read_text(encoding="utf-8"))[
        "items"
    ][0]["model_claim"]


def test_a_step_with_no_todo_touches_nothing(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    notes = apply_step_todo_facts(project, [{"tool": "read_file", "path": "a"}])
    assert notes == []
    assert not (project / ".ract" / "todo.json").exists()


def test_stepwork_carries_todo_facts() -> None:
    work = StepWork()
    assert work.todo_facts == []


def test_apply_todo_facts_still_works_on_a_plain_list() -> None:
    todo = TodoList()
    note = apply_todo_facts(todo, {"todo_op": {"op": "add", "text": "x"}})
    assert note == "added item 1"
