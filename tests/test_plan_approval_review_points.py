"""B-064c, the five points of the BUILDER's review (L-196), one test each where the point is testable.

1. An edit reaches the run (the step's request carries the edited text, not the model's).
2. A remembered approval keeps its skips on resume.
3. Approvals live in the user state directory; a planted session file never skips the question.
4. The path guess strips trailing punctuation and wants a path shape.
5. An edit announces the plan again, with its new hash.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract import approval_callback, plan_approval_store, plan_gate, ract_runner
from ract.core import keys
from ract.harness import _plan_with_shown_actions
from ract.manager import Plan, Step as PlanStep
from ract.ui.plan_approval_view import Step, plan_hash
from tests.test_plan_approval_wiring import PLAN, _harness, _run

SHOWN_PLAN = [Step(1, "Create a", "a.txt"), Step(2, "Create b", "b.txt")]


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setattr(keys, "_default_state_dir", lambda: state)
    return state


def test_point_1_the_edited_text_reaches_the_step_request(tmp_path, monkeypatch):
    harness = _harness(tmp_path, PLAN, "aaa", "bbb")
    result, events, _, _ = _run(
        harness,
        monkeypatch,
        ["edit 1", "Create a, written as the file a.txt with one line", "approve"],
    )
    assert result.is_ok(), result.error
    sent = [
        str(call.args[0] if call.args else call.kwargs)
        for call in harness.manager.provider.complete.call_args_list
    ]
    assert any("written as the file a.txt with one line" in text for text in sent)
    assert not any("Task: Create a\n" in text for text in sent)


def test_point_1_the_plan_by_number_takes_the_shown_text():
    plan = Plan(
        assumption="x",
        confidence=1.0,
        steps=[
            PlanStep(
                action="Create a", provider_hint="local", expected_artifact="a.txt"
            ),
            PlanStep(
                action="Create b", provider_hint="local", expected_artifact="b.txt"
            ),
        ],
    )
    edited = _plan_with_shown_actions(
        plan, [Step(1, "Create a, edited", "a.txt"), Step(2, "Create b", "b.txt")]
    )
    assert edited.steps[0].action == "Create a, edited"
    assert edited.steps[1].action == "Create b"
    assert plan.steps[0].action == "Create a"  # the original is not changed in place


def test_point_2_a_remembered_approval_keeps_its_skips_on_resume(
    tmp_path, state_dir, monkeypatch
):
    plan = Plan(
        assumption="x",
        confidence=1.0,
        steps=[
            PlanStep(
                action=f"Create {n}",
                provider_hint="local",
                expected_artifact=f"{n}.txt",
            )
            for n in "abc"
        ],
    )
    steps = [
        Step(n, f"Create {ch}", f"{ch}.txt") for n, ch in enumerate("abc", start=1)
    ]
    monkeypatch.setattr(approval_callback, "_plan_steps", lambda p: list(steps))
    outcome = plan_gate.Resolution(
        "approved",
        kept=steps[:2],
        skipped=[steps[2]],
        shown=list(steps),
    )
    wrapped = ract_runner._remembering_approval(
        lambda p: outcome, tmp_path / "ract.yaml", "s-1"
    )
    wrapped(plan)
    assert plan_hash(steps) in plan_approval_store.load(tmp_path, "s-1")
    skipped = ract_runner._approvals_for_resume(
        tmp_path / "ract.yaml", "s-1", True, plan
    )
    assert skipped == frozenset({3})


def test_point_2_a_fresh_run_takes_no_remembered_skips(
    tmp_path, state_dir, monkeypatch
):
    plan_approval_store.remember(tmp_path, "s-1", "f" * 64, [1])
    plan = Plan(assumption="x", confidence=1.0, steps=[])
    assert (
        ract_runner._approvals_for_resume(tmp_path / "ract.yaml", "s-1", False, plan)
        == frozenset()
    )


def test_point_3_a_planted_session_file_does_not_skip_the_question(
    tmp_path, state_dir, monkeypatch
):
    # A cloned repository ships a session file that lists the hash of a plan it never ran.
    steps = list(SHOWN_PLAN)
    monkeypatch.setattr(approval_callback, "_plan_steps", lambda p: list(steps))
    planted = tmp_path / ".ract" / "sessions"
    planted.mkdir(parents=True)
    (planted / "s-1.json").write_text(
        json.dumps({"intent": "x", "plan": {}, "plan_approvals": [plan_hash(steps)]}),
        encoding="utf-8",
    )
    assert plan_approval_store.load(tmp_path, "s-1") == {}
    plan = Plan(assumption="x", confidence=1.0, steps=[])
    assert (
        ract_runner._approvals_for_resume(tmp_path / "ract.yaml", "s-1", True, plan)
        == frozenset()
    )
    # The approval the user state directory holds is what counts.
    assert plan_approval_store.approvals_path(tmp_path, "s-1").is_relative_to(state_dir)


def test_point_3_a_session_id_that_is_not_a_name_is_refused(tmp_path, state_dir):
    with pytest.raises(ValueError):
        plan_approval_store.approvals_path(tmp_path, "../escape")


def test_point_4_a_sentence_with_a_trailing_letter_is_not_a_path():
    assert plan_gate._path_candidates("make add return a + b.") == []
    assert plan_gate._path_candidates("edit src/calc.py and tests/t.py,") == [
        "src/calc.py",
        "tests/t.py",
    ]
    assert plan_gate._path_candidates("set x to 1.5 units") == []


def test_point_5_an_edit_announces_the_plan_again_with_its_new_hash(
    tmp_path, monkeypatch
):
    harness = _harness(tmp_path, PLAN, "aaa", "bbb")
    _, events, _, _ = _run(
        harness,
        monkeypatch,
        ["edit 1", "Create a, written as the file a.txt with one line", "approve"],
    )
    requested = [d["plan_hash"] for k, d in events if k == "plan.approval_requested"]
    proposed = [k for k, _ in events if k == "plan.proposed"]
    assert len(requested) == 2 and requested[0] != requested[1]
    assert len(proposed) >= 2
    answered = dict(events)["plan.approval_answered"]
    assert answered["edited"] == 1
