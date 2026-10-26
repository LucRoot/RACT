"""B-053a: the plan as a live checklist in the plain renderer.

A plan with two or more steps prints a checklist block, reprints a step's line
as it starts and ends, and prints the final state once more at the end of the
turn. A one-step plan keeps the short lines.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from ract.session_events import EventStream
from ract.session_render import PlainRenderer

MARKS = ("Plan (", "[ ]", "[>]", "[x]", "[!]", "[-]")


def _stream() -> EventStream:
    return EventStream(
        session="s-1",
        clock=lambda: datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc),
    )


def _render(*events: tuple[str, dict[str, Any]], width: int = 80) -> str:
    out = io.StringIO()
    stream = _stream()
    renderer = PlainRenderer(out.write, width=width)
    stream.subscribe(renderer)
    for kind, data in events:
        stream.emit(kind, data, turn=1)
    renderer.close()
    return out.getvalue()


def _checklist(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(MARKS)]


def _plan(*actions: str, targets: tuple[str | None, ...] | None = None) -> tuple:
    steps = []
    for i, action in enumerate(actions, start=1):
        target = targets[i - 1] if targets else f"{chr(96 + i)}.py"
        steps.append({"n": i, "action": action, "target": target})
    return ("plan.proposed", {"assumption": "", "confidence": 0.9, "steps": steps})


def _started(n: int, action: str, target: str | None) -> tuple:
    return ("step.started", {"n": n, "action": action, "target": target})


def _finished(n: int, outcome: str, **extra: Any) -> tuple:
    data = {"n": n, "outcome": outcome, "duration_ms": 1200, **extra}
    return ("step.finished", data)


def test_three_steps_all_done_print_the_checklist_in_order():
    text = _render(
        _plan("edit a", "edit b", "edit c"),
        _started(1, "edit a", "a.py"),
        _finished(1, "done", artifact="a.py"),
        _started(2, "edit b", "b.py"),
        _finished(2, "done", artifact="b.py"),
        _started(3, "edit c", "c.py"),
        _finished(3, "done", artifact="c.py"),
        ("turn.finished", {"outcome": "done", "verdict": "passed", "changed": []}),
    )
    assert _checklist(text) == [
        "Plan (3 steps):",
        "[ ] 1. edit a -> a.py",
        "[ ] 2. edit b -> b.py",
        "[ ] 3. edit c -> c.py",
        "[>] 1. edit a -> a.py",
        "[x] 1. edit a -> a.py (1.2s) passed",
        "[>] 2. edit b -> b.py",
        "[x] 2. edit b -> b.py (1.2s) passed",
        "[>] 3. edit c -> c.py",
        "[x] 3. edit c -> c.py (1.2s) passed",
        "Plan (3 steps), final:",
        "[x] 1. edit a -> a.py (1.2s) passed",
        "[x] 2. edit b -> b.py (1.2s) passed",
        "[x] 3. edit c -> c.py (1.2s) passed",
    ]


def test_failed_step_shows_its_hint_and_a_skipped_step_shows_skipped():
    text = _render(
        _plan("edit a", "edit b", "edit c"),
        _started(1, "edit a", "a.py"),
        _finished(1, "done", artifact="a.py"),
        _started(2, "edit b", "b.py"),
        _finished(2, "failed", hint="tests broke in b.py"),
        _finished(3, "skipped"),
        ("turn.finished", {"outcome": "failed", "verdict": "failed", "changed": []}),
    )
    lines = _checklist(text)
    assert "[!] 2. edit b -> b.py (1.2s) failed" in lines
    assert "[-] 3. edit c -> c.py (1.2s) skipped" in lines
    assert "  hint: tests broke in b.py" in text.splitlines()


def test_refused_step_shows_the_policy_hint():
    text = _render(
        _plan("edit a", "edit b"),
        _started(1, "edit a", "a.py"),
        _finished(1, "refused", hint="outside the workspace"),
    )
    assert "[!] 1. edit a -> a.py (1.2s) refused" in text.splitlines()
    assert "  hint: outside the workspace" in text.splitlines()


def test_answer_step_has_no_path_and_shows_answer():
    text = _render(
        _plan("explain the module", "edit b", targets=(None, "b.py")),
        _started(1, "explain the module", None),
        _finished(1, "done"),
    )
    assert "[ ] 1. explain the module -> answer" in text.splitlines()
    assert "[x] 1. explain the module -> answer (1.2s) passed" in text.splitlines()


def test_interrupted_turn_marks_steps_that_never_ran_as_skipped():
    # D1: a step that was running or never started when the turn stopped is skipped.
    text = _render(
        _plan("edit a", "edit b", "edit c"),
        _started(1, "edit a", "a.py"),
        _finished(1, "done", artifact="a.py"),
        _started(2, "edit b", "b.py"),
        ("turn.finished", {"outcome": "interrupted", "verdict": "", "changed": []}),
    )
    final = _checklist(text)[-3:]
    assert final == [
        "[x] 1. edit a -> a.py (1.2s) passed",
        "[-] 2. edit b -> b.py (0.0s) skipped",
        "[-] 3. edit c -> c.py (0.0s) skipped",
    ]


def test_long_action_is_cut_to_the_width_and_escape_bytes_are_inert():
    action = "rewrite the module \x1b[31mred\x1b[0m " + "x" * 300
    text = _render(
        _plan(action, "edit b"),
        _started(1, action, "a.py"),
        _finished(1, "done", artifact="a.py"),
    )
    assert "\x1b" not in text
    for line in _checklist(text):
        assert len(line) <= 80
    assert any("..." in line for line in _checklist(text))


def test_no_line_is_wider_than_sixty_or_eighty_columns():
    action = "change " + "y" * 200
    for width in (60, 80):
        text = _render(
            _plan(action, "edit b"),
            _started(1, action, "a.py"),
            _finished(1, "done", artifact="a.py"),
            width=width,
        )
        for line in _checklist(text):
            assert len(line) <= width, (width, line)


def test_one_step_plan_keeps_the_short_lines_and_no_checklist():
    text = _render(
        _plan("edit a"),
        _started(1, "edit a", "a.py"),
        _finished(1, "done", artifact="a.py"),
    )
    assert "[step 1] edit a -> a.py" in text
    assert _checklist(text) == []
