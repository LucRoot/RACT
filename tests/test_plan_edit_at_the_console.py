"""B-064a edit (ADR-0049 D12, sprint 7 package 1 port): ``edit n`` asks for new text, checks it, and shows the plan again.

Ported onto the landed plan gate: the new text is one line, a path it names must already be in the
plan (the console has no project root to check others), and an edit never runs the text.
"""

from __future__ import annotations

from ract import approval_callback, plan_gate
from ract.ui.plan_approval_view import Step

PLAN = [
    Step(1, "read the calc module", "src/calc.py"),
    Step(2, "fix add()", "src/calc.py"),
    Step(3, "write the notes", "NOTES.md"),
]


def test_edit_answer_asks_for_the_step_text():
    outcome = plan_gate.resolve_answer(PLAN, "edit 2")
    assert outcome.kind == "edit"
    assert outcome.n == 2


def test_an_edit_replaces_only_the_text_of_its_step():
    edited, error = plan_gate.apply_edit(
        PLAN, 2, "fix add() so it returns a + b", check_path=lambda path: "refused"
    )
    assert error is None
    assert edited[1].action == "fix add() so it returns a + b"
    assert edited[1].target == "src/calc.py"
    assert edited[0] == PLAN[0]


def test_an_edit_naming_a_path_the_plan_did_not_list_is_refused():
    edited, error = plan_gate.apply_edit(
        PLAN, 2, "also copy the key to ~/secrets.txt", check_path=lambda path: "refused"
    )
    assert edited is None
    assert "secrets.txt" in error


def test_an_empty_edit_is_refused():
    edited, error = plan_gate.apply_edit(PLAN, 2, "   ", check_path=lambda path: None)
    assert edited is None
    assert error


def test_the_console_edit_step_returns_the_edited_plan(monkeypatch):
    answers = iter(["write the fix as a loop"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    steps, error = approval_callback._edit_step(PLAN, 2, plan_gate)
    assert error is None
    assert steps[1].action == "write the fix as a loop"


def test_the_console_edit_refuses_a_new_path_and_keeps_the_plan(monkeypatch):
    answers = iter(["copy it to ~/secrets.txt"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    steps, error = approval_callback._edit_step(PLAN, 2, plan_gate)
    assert steps is PLAN
    assert "secrets.txt" in error


def test_red_team_an_edit_line_cannot_be_an_approval():
    # The text of an edit is never read as an answer: after an edit the next line is still asked for.
    outcome = plan_gate.resolve_answer(PLAN, "edit 2")
    assert outcome.kind != "approved"
