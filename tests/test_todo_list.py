"""B-177 first slice: the to-do list, its view, and the ``todo`` tool (not yet registered).

A model's claim never ticks an item; only a check that passed does. The list survives a save and a load
(the ``/resume`` case). The view keeps the plan checklist's markers and fits 80, 60 and 40 columns.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ract.core.threat_model import CapabilityTier
from ract.todo_list import (
    TodoList,
    apply_todo_facts,
    load,
    save,
    todo_lines,
)
from ract.tools import ToolRefused
from ract.tools.todo_tool import TODO_TOOL, TodoArgs, run_todo

WIDTHS = (80, 60, 40)


def test_an_added_item_is_open_and_numbered_from_one() -> None:
    todo = TodoList()
    first = todo.add("write the parser test")
    second = todo.add("update the changelog")
    assert (first.id, second.id) == (1, 2)
    assert first.state == "open" and not first.model_claim and first.evidence is None


def test_a_model_claim_of_done_does_not_tick_the_item() -> None:
    todo = TodoList()
    item = todo.add("fix the loop")
    todo.claim_done(item.id)
    assert item.state == "open"
    assert item.model_claim is True
    assert item.evidence is None


def test_a_passing_check_ticks_the_item_with_its_evidence() -> None:
    todo = TodoList()
    item = todo.add("the tests pass")
    todo.tick(item.id, "tests/test_loop.py: 12 passed")
    assert item.state == "done"
    assert item.evidence == "tests/test_loop.py: 12 passed"


def test_a_claim_made_after_the_evidence_keeps_the_item_done() -> None:
    todo = TodoList()
    item = todo.add("the build runs")
    todo.tick(item.id, "build: exit 0")
    todo.claim_done(item.id)
    assert item.state == "done" and item.evidence == "build: exit 0"


def test_a_tick_needs_evidence() -> None:
    todo = TodoList()
    item = todo.add("the tests pass")
    with pytest.raises(ValueError):
        todo.tick(item.id, "   ")
    assert item.state == "open"


def test_a_dropped_item_cannot_be_ticked_and_a_done_one_cannot_be_dropped() -> None:
    todo = TodoList()
    dropped = todo.add("maybe later")
    todo.drop(dropped.id)
    with pytest.raises(ValueError):
        todo.tick(dropped.id, "check: passed")
    done = todo.add("finished")
    todo.tick(done.id, "check: passed")
    with pytest.raises(ValueError):
        todo.drop(done.id)


def test_the_list_survives_a_save_and_a_load(tmp_path) -> None:
    todo = TodoList()
    todo.add("first")
    item = todo.add("second")
    todo.tick(item.id, "tests: passed")
    todo.claim_done(1)
    save(todo, tmp_path)
    again = load(tmp_path)
    assert [
        (i.id, i.text, i.state, i.model_claim, i.evidence) for i in again.items
    ] == [(i.id, i.text, i.state, i.model_claim, i.evidence) for i in todo.items]
    assert again.next_id == todo.next_id


def test_a_missing_file_loads_as_an_empty_list(tmp_path) -> None:
    assert load(tmp_path).items == []


def test_a_damaged_file_is_an_error_not_an_empty_list(tmp_path) -> None:
    (tmp_path / "todo.json").write_text(
        json.dumps({"items": "not a list"}), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load(tmp_path)


def test_a_model_cannot_name_a_done_operation() -> None:
    todo = TodoList()
    todo.add("x")
    with pytest.raises(ValueError):
        apply_todo_facts(todo, {"todo_op": {"op": "done", "id": 1}})


def test_apply_facts_adds_claims_and_drops() -> None:
    todo = TodoList()
    assert (
        apply_todo_facts(todo, {"todo_op": {"op": "add", "text": "read the file"}})
        == "added item 1"
    )
    apply_todo_facts(todo, {"todo_op": {"op": "claim_done", "id": 1}})
    assert todo.get(1).model_claim is True and todo.get(1).state == "open"
    apply_todo_facts(todo, {"todo_op": {"op": "drop", "id": 1}})
    assert todo.get(1).state == "dropped"


@pytest.mark.parametrize("width", WIDTHS)
def test_the_view_fits_and_uses_the_checklist_markers(width: int) -> None:
    todo = TodoList()
    todo.add("write the design page for the spec flow in plain words, one page")
    done = todo.add("tests pass")
    todo.tick(done.id, "tests/test_todo_list.py: 20 passed")
    todo.claim_done(1)
    todo.add("drop me")
    todo.drop(3)
    lines = todo_lines(todo, width)
    assert all(len(line) <= width for line in lines), lines
    text = "\n".join(lines)
    assert "[?] 1." in text and "[x] 2." in text and "[-] 3." in text
    assert "model says done, not checked" in text
    assert "checked: tests/test_todo_list.py: 20 passed" in " ".join(text.split())


def test_the_view_has_no_escape_sequence_and_shows_a_control_character_as_an_escape() -> (
    None
):
    todo = TodoList()
    todo.add("run \x1b[31mred\x07 now")
    text = "\n".join(todo_lines(todo, 80))
    assert "\x1b" not in text and "\x07" not in text
    assert "\\x1b" in text and "\\x07" in text


def test_an_empty_list_says_so() -> None:
    assert "nothing on the list yet" in todo_lines(TodoList(), 80)[1]


def test_the_tool_is_tier_zero_and_does_not_mutate() -> None:
    assert TODO_TOOL.tier is CapabilityTier.TIER_0_READ
    assert TODO_TOOL.mutates is False


def test_the_tool_refuses_an_extra_field() -> None:
    with pytest.raises(ValidationError):
        TodoArgs(op="add", text="x", owner="model")


def test_the_tool_needs_text_to_add_and_an_id_to_claim_or_drop() -> None:
    with pytest.raises(ToolRefused):
        run_todo(None, TodoArgs(op="add", text="  "))
    with pytest.raises(ToolRefused):
        run_todo(None, TodoArgs(op="claim_done"))
    with pytest.raises(ToolRefused):
        run_todo(None, TodoArgs(op="drop"))


def test_the_tool_returns_its_operation_as_facts_and_writes_nothing() -> None:
    result = run_todo(None, TodoArgs(op="add", text="write the summary"))
    assert result.facts == {"todo_op": {"op": "add", "text": "write the summary"}}
    claim = run_todo(None, TodoArgs(op="claim_done", id=2))
    assert claim.facts == {"todo_op": {"op": "claim_done", "id": 2}}
    assert "stays open until a check passes" in claim.text
