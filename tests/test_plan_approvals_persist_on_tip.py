"""D12 persistence, ported onto the landed plan gate: a resumed session does not ask again for an approved plan.

The approval is keyed by ``plan_hash`` of the steps the operator saw. A changed plan (a new
hash) is asked again. A refusal records nothing.
"""

from __future__ import annotations

from ract import approval_callback, plan_gate, ract_runner
from ract.session_store import SessionState
from ract.ui.plan_approval_view import Step

STEPS = [Step(1, "read", "src/calc.py"), Step(2, "fix", "src/calc.py")]


HOLD: dict = {"steps": STEPS}


def _use(monkeypatch, steps):
    # The wrapper binds _plan_steps when it is made, so the stub reads HOLD on every call.
    HOLD["steps"] = list(steps)
    monkeypatch.setattr(approval_callback, "_plan_steps", lambda plan: list(HOLD["steps"]))


def test_an_approved_plan_is_remembered_and_not_asked_again(monkeypatch):
    _use(monkeypatch, STEPS)
    known: list[str] = []
    asked = []

    def ask(plan):
        asked.append(plan)
        return plan_gate.Resolution("approved", kept=list(STEPS))

    once = ract_runner._persisting_approval(ask, known)
    assert once(object()).kind == "approved"
    assert len(known) == 1 and len(asked) == 1
    # The same plan on the next call (or a resumed session holding the hash): no question.
    assert once(object()).kind == "approved"
    assert len(asked) == 1


def test_a_changed_plan_is_asked_again(monkeypatch):
    known: list[str] = []
    asked = []

    def ask(plan):
        asked.append(plan)
        return plan_gate.Resolution("approved", kept=list(STEPS))

    _use(monkeypatch, STEPS)
    once = ract_runner._persisting_approval(ask, known)
    once(object())
    _use(monkeypatch, [Step(1, "read", "src/calc.py"), Step(2, "fix it differently", "src/calc.py")])
    once(object())
    assert len(asked) == 2


def test_a_refusal_records_nothing(monkeypatch):
    _use(monkeypatch, STEPS)
    known: list[str] = []

    def ask(plan):
        return plan_gate.Resolution("refused")

    once = ract_runner._persisting_approval(ask, known)
    assert once(object()).kind == "refused"
    assert known == []


def test_the_saved_approvals_round_trip_through_the_session_state():
    state = SessionState(intent="x", plan=None, plan_approvals=["abc"])
    assert state.plan_approvals == ["abc"]
    assert SessionState(intent="x", plan=None).plan_approvals == []


def test_red_team_a_saved_hash_for_another_plan_does_not_skip_the_question(monkeypatch):
    _use(monkeypatch, STEPS)
    known = ["0" * 64]
    asked = []

    def ask(plan):
        asked.append(plan)
        return plan_gate.Resolution("refused")

    once = ract_runner._persisting_approval(ask, known)
    assert once(object()).kind == "refused"
    assert len(asked) == 1
