"""Package 2 (B-064a, ADR-0049 D12): when a plan is approved before its first step.

In default mode a plan of two or more steps that changes files asks once. A one-step plan keeps the
per-step approval. accept-edits and plan modes never ask. A plan of answer steps only never asks.
Headless default refuses a plan with file changes (exit 3) and names --accept-edits.
"""

from __future__ import annotations

from ract.plan_gate import approval_needed, headless_refusal
from ract.ui.plan_approval_view import Step


def _steps(n: int, target: str = "src/a.py"):
    return [Step(n=i + 1, action=f"step {i + 1}", target=target) for i in range(n)]


def test_default_mode_asks_for_a_two_step_plan_with_file_changes():
    assert approval_needed(_steps(2), mode="default") is True


def test_a_one_step_plan_keeps_the_per_step_approval_and_does_not_ask_once():
    assert approval_needed(_steps(1), mode="default") is False


def test_accept_edits_and_plan_modes_never_ask():
    assert approval_needed(_steps(3), mode="accept-edits") is False
    assert approval_needed(_steps(3), mode="plan") is False


def test_a_plan_of_answer_steps_only_never_asks():
    assert approval_needed(_steps(3, target=""), mode="default") is False


def test_headless_default_refuses_a_plan_with_file_changes_and_names_the_flag():
    sentence = headless_refusal(_steps(2), mode="default")
    assert sentence is not None and "--accept-edits" in sentence
    assert headless_refusal(_steps(2), mode="accept-edits") is None
    assert headless_refusal(_steps(3, target=""), mode="default") is None


def test_an_approve_answer_keeps_every_step():
    from ract.plan_gate import resolve_answer

    outcome = resolve_answer(_steps(3), "approve")
    assert outcome.kind == "approved"
    assert [s.n for s in outcome.kept] == [1, 2, 3]
    assert outcome.skipped == []


def test_skip_drops_the_step_and_the_later_steps_that_depend_on_its_file():
    from ract.plan_gate import resolve_answer

    steps = [
        Step(n=1, action="a", target="src/a.py"),
        Step(n=2, action="b", target="src/b.py"),
        Step(n=3, action="c", target="src/b.py"),
    ]
    outcome = resolve_answer(steps, "skip 2")
    assert outcome.kind == "approved"
    assert [s.n for s in outcome.kept] == [1]
    assert [s.n for s in outcome.skipped] == [2, 3]


def test_cancel_keeps_nothing_and_refuses_the_turn():
    from ract.plan_gate import resolve_answer

    outcome = resolve_answer(_steps(3), "cancel")
    assert outcome.kind == "refused"
    assert outcome.kept == []


def test_an_answer_that_is_not_understood_asks_again():
    from ract.plan_gate import resolve_answer

    outcome = resolve_answer(_steps(3), "rm -rf /")
    assert outcome.kind == "ask_again"
    assert outcome.error


def test_a_plan_approved_with_the_same_hash_is_not_asked_again_on_resume():
    from ract.plan_gate import ApprovalMemory

    memory = ApprovalMemory()
    steps = _steps(3)
    assert memory.needs_approval(steps, mode="default") is True
    memory.record(steps)
    assert memory.needs_approval(steps, mode="default") is False


def test_a_changed_plan_asks_again():
    from ract.plan_gate import ApprovalMemory

    memory = ApprovalMemory()
    memory.record(_steps(3))
    assert memory.needs_approval(_steps(3, target="src/other.py"), mode="default") is True


def test_the_memory_restores_from_saved_hashes():
    from ract.plan_gate import ApprovalMemory

    first = ApprovalMemory()
    first.record(_steps(3))
    restored = ApprovalMemory(saved=first.hashes())
    assert restored.needs_approval(_steps(3), mode="default") is False


def test_the_two_plan_kinds_are_registered_in_the_session_stream():
    from ract.session_events import KINDS

    assert "plan.approval_requested" in KINDS
    assert "plan.approval_answered" in KINDS


def test_approval_requested_carries_the_hash_and_the_steps():
    from ract.plan_gate import approval_requested_payload

    payload = approval_requested_payload(_steps(2))
    assert set(payload) == {"plan_hash", "steps"}
    assert payload["steps"][0] == {"n": 1, "action": "step 1", "target": "src/a.py"}
    assert len(payload["plan_hash"]) == 64


def test_approved_payload_reasons_follow_d12_user_or_depends_on_step():
    from ract.plan_gate import answered_payload, resolve_answer

    steps = [
        Step(n=1, action="a", target="src/a.py"),
        Step(n=2, action="b", target="src/b.py"),
        Step(n=3, action="writes src/b.py too", target="src/c.py"),
    ]
    outcome = resolve_answer(steps, "skip 2")
    payload = answered_payload(steps, "skip", outcome)
    assert payload["answer"] == "skip"
    assert payload["kept"] == [1]
    assert payload["skipped"] == [
        {"n": 2, "reason": "user"},
        {"n": 3, "reason": "depends on step 2"},
    ]
