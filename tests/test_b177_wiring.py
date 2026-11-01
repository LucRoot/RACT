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


def test_the_model_cannot_drop_an_item_the_plan_wrote(tmp_path: Path) -> None:
    import pytest

    from ract.todo_list import TodoList, apply_todo_facts

    todo = TodoList()
    plan_item = todo.add("keep the changelog fresh", origin="plan")
    model_item = todo.add("a model's own note")
    with pytest.raises(ValueError, match="comes from the plan"):
        apply_todo_facts(todo, {"todo_op": {"op": "drop", "id": plan_item.id}})
    apply_todo_facts(todo, {"todo_op": {"op": "drop", "id": model_item.id}})
    assert todo.items[0].state == "open"
    assert todo.items[1].state == "dropped"


def test_save_refuses_a_path_through_a_link(tmp_path: Path) -> None:
    import pytest

    from ract.todo_list import TodoList, save

    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not creatable here")
    with pytest.raises(Exception):
        save(TodoList(), linked)
