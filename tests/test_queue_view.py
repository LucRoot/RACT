"""B-033a and B-033b, prepared (package J): the queue as pure data and text.

Unwired on purpose: the module reads no key and emits no event. Tests cover the model
(order, ids), the indicator, the list and the drop result, at 80, 60 and 40 columns,
plain and rich, and that the module imports nothing from the input handling or the
event layer.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from rich.cells import cell_len

from ract.ui import queue_view as qv

WIDTHS = (80, 60, 40)


def _model(*texts: str) -> qv.QueueModel:
    model = qv.QueueModel()
    for text in texts:
        model = model.append(text)
    return model


def test_lines_keep_their_order_and_ids_never_repeat():
    model = _model("add tests", "update README")
    assert [(i.id, i.text) for i in model.items] == [(1, "add tests"), (2, "update README")]
    model, removed = model.drop(1)
    model = model.append("third")
    assert [i.id for i in model.items] == [2, 3]
    assert removed.id == 1


def test_up_takes_the_last_line_back_for_editing():
    model, last = _model("a", "b").take_last()
    assert last is not None and last.text == "b"
    assert [i.text for i in model.items] == ["a"]
    empty, nothing = qv.QueueModel().take_last()
    assert nothing is None and empty.items == ()


@pytest.mark.parametrize("count, text", [(0, ""), (1, "1 queued"), (2, "2 queued")])
def test_the_indicator_says_how_many_are_queued(count, text):
    assert qv.indicator(count) == text
    assert qv.indicator(count, rich=True) == (f"[dim]{text}[/dim]" if text else "")


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("rich", [False, True])
def test_the_list_fits_the_width_and_shows_every_line(width, rich):
    model = _model("add a greeting to src/calc.py and two tests " * 2, "update README.md")
    lines = qv.list_lines(model, width, rich=rich)
    plain = [line.replace("[dim]", "").replace("[/dim]", "") for line in lines]
    for line in plain:
        assert cell_len(line) <= width, (width, line)
    assert plain[0] == "queue (2):"
    assert any(line.lstrip().startswith("2. update README.md") for line in plain)


def test_an_empty_queue_says_so_and_names_what_fills_it():
    lines = qv.list_lines(qv.QueueModel(), 60)
    assert lines == ["queue is empty; lines you type while a turn runs appear here"]


@pytest.mark.parametrize("width", WIDTHS)
def test_drop_removes_the_numbered_line_and_says_which(width):
    model = _model("first", "second", "third")
    model, lines = qv.drop_message(model, "2", width)
    assert [i.text for i in model.items] == ["first", "third"]
    assert lines == ["dropped 2: second"]


@pytest.mark.parametrize("width", WIDTHS)
def test_drop_errors_change_nothing_and_say_what_to_do(width):
    model = _model("only")
    same, lines = qv.drop_message(model, "", width)
    assert same == model and "usage: /queue drop <n>" in lines[0]
    same, lines = qv.drop_message(model, "x", width)
    assert same == model and "'x' is not a number" in lines[0]
    same, lines = qv.drop_message(model, "9", width)
    assert same == model and "no queued line 9; the queue has 1" in lines[0]
    same, lines = qv.drop_message(qv.QueueModel(), "1", width)
    assert same.items == () and lines[0] == "the queue is empty; nothing to drop"


def test_the_module_imports_nothing_from_input_handling_or_events():
    source = Path(qv.__file__).read_text(encoding="utf-8")
    names = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import) for alias in node.names
    }
    for forbidden in ("repl", "session_events", "approval_callback", "input", "readline", "session_render"):
        assert not any(name.endswith(forbidden) for name in names), names
    assert ".emit(" not in source
