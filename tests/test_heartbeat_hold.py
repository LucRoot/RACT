"""Adjudication row 5: no heartbeat line lands on an open approval question.

Interim fix (B-033s owns the input design): the approval prompt marks the
question open while it waits for an answer, and the plain renderer holds its
heartbeat lines while the mark is set. Tested at 80, 60 and 40 columns.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest

from ract import question_gate
from ract.session_events import EventStream
from ract.session_render import PlainRenderer


def _heartbeat_lines(width: int, held: bool) -> list[str]:
    out = io.StringIO()
    stream = EventStream(
        session="s-1",
        clock=lambda: datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc),
    )
    renderer = PlainRenderer(out.write, width=width)
    stream.subscribe(renderer)
    if held:
        question_gate.open_question()
    try:
        stream.emit(
            "agent.heartbeat", {"elapsed_ms": 4000, "waiting_on": "model"}, turn=1
        )
    finally:
        question_gate.close_question()
    renderer.close()
    return [line for line in out.getvalue().splitlines() if "waiting on model" in line]


@pytest.mark.parametrize("width", [80, 60, 40])
def test_a_heartbeat_is_held_while_an_approval_question_is_open(width):
    assert _heartbeat_lines(width, held=True) == []


@pytest.mark.parametrize("width", [80, 60, 40])
def test_a_heartbeat_prints_again_once_the_question_is_answered(width):
    assert len(_heartbeat_lines(width, held=False)) == 1


def test_the_approval_callback_marks_the_question_open_while_it_waits(
    monkeypatch, capsys
):
    from ract.approval_callback import console_approval_callback
    from ract.manager import Step

    seen: list[bool] = []

    def fake_input(prompt=""):
        seen.append(question_gate.question_open())
        return "y"

    monkeypatch.setattr("builtins.input", fake_input)
    step = Step(
        action="fix add", provider_hint="local", expected_artifact="src/calc.py"
    )
    assert console_approval_callback(step) is True
    assert seen == [True]
    assert question_gate.question_open() is False
