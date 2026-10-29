"""Sprint 7 package 4 (red team of the plan gate and the approval memory), one attack per test.

Attacks: a saved approval for a 200-step plan replayed on the same plan with one step changed;
skip and edit at the ends of a 200-step plan; an answer that arrives after a cancel; an edit
text carrying an escape sequence; an edit text that reads like an approval.
"""

from __future__ import annotations

from ract import approval_callback, plan_approval_store, plan_gate, ract_runner
from ract.session_events import safe_text
from ract.ui.plan_approval_view import Step, plan_hash

BIG = [Step(n, f"step {n}", f"src/part{n}.py") for n in range(1, 201)]
SMALL = [Step(1, "read", "src/calc.py"), Step(2, "fix", "src/calc.py"), Step(3, "notes", "NOTES.md")]


def test_a_saved_hash_of_a_200_step_plan_does_not_match_the_same_plan_with_one_step_changed():
    changed = list(BIG)
    changed[199] = Step(200, "step 200, now different", "src/part200.py")
    assert plan_hash(BIG) != plan_hash(changed)


def test_skip_at_the_ends_of_a_200_step_plan_is_in_range():
    assert plan_gate.resolve_answer(BIG, "skip 200").kind == "approved"
    assert plan_gate.resolve_answer(BIG, "skip 201").kind == "ask_again"
    assert plan_gate.resolve_answer(BIG, "edit 200").kind == "edit"
    assert plan_gate.resolve_answer(BIG, "edit 0").kind == "ask_again"


def test_an_answer_after_a_cancel_is_not_remembered_as_an_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(approval_callback, "_plan_steps", lambda plan: list(SMALL))
    asked = []

    def ask(plan):
        asked.append(plan)
        return plan_gate.resolve_answer(SMALL, "cancel")

    once = ract_runner._remembering_approval(ask, tmp_path / "ract.yaml", "s-1")
    assert once(object()).kind == "refused"
    assert plan_approval_store.load(tmp_path, "s-1") == {}
    assert once(object()).kind == "refused"
    assert len(asked) == 2


def test_an_edit_text_with_an_escape_sequence_stays_text_and_is_shown_without_it():
    edited, error = plan_gate.apply_edit(
        SMALL, 2, "fix\x1b[2J add", check_path=lambda path: "refused"
    )
    assert error is None
    assert "\x1b" in edited[1].action  # kept as the operator's text
    assert "\x1b" not in safe_text(edited[1].action)  # never printed raw


def test_an_edit_text_that_reads_like_an_approval_is_still_a_step_text(monkeypatch):
    edited, error = plan_gate.apply_edit(
        SMALL, 2, "approve", check_path=lambda path: "refused"
    )
    assert error is None
    assert edited[1].action == "approve"
    # The plan is not approved by its own text: the next answer line decides.
    assert plan_gate.resolve_answer(edited, "approve").kind == "approved"
    assert plan_gate.resolve_answer(SMALL, "approve").kind == "approved"
