"""Package 5 (handoff 1): an interrupted step is skipped, not failed.

Ctrl-C at the approval prompt used to record "[!] 1. ... failed" before "stopping...". The
renderer already shows a stopped step as skipped (plan_state: turn.finished sets pending or
running steps to skipped), so the executor must report the same outcome.
"""

from __future__ import annotations

from ract.executor.steps import unfinished_step_outcome


def test_an_interrupted_unfinished_step_is_skipped():
    assert (
        unfinished_step_outcome("Approval denied for step", cancelled=True) == "skipped"
    )
    assert unfinished_step_outcome("", cancelled=True) == "skipped"


def test_a_refused_unfinished_step_is_refused():
    assert unfinished_step_outcome("refused by policy", cancelled=False) == "refused"


def test_any_other_unfinished_step_is_failed():
    assert unfinished_step_outcome("provider timed out", cancelled=False) == "failed"


def test_ctrl_c_at_the_approval_prompt_ends_the_step_skipped_not_failed(
    tmp_path, monkeypatch
):
    # Adjudication row 6 (D-068). On Windows, Ctrl-C while the turn's worker waits in
    # input() raises KeyboardInterrupt in the main thread, which cancels the turn, and
    # ends the worker's read with EOFError. When the EOF won the race, the step was
    # reported failed before the cancel arrived ("[!] 1. ... failed" then "stopping").
    import threading

    from ract import turn_context
    from ract.approval_callback import console_approval_callback
    from ract.executor import Executor
    from ract.manager import Plan, Step
    from ract.plan_state import PlanState
    from tests.test_executor import FakeAdapter, FakeRouter

    cancel = turn_context.CancelSignal()

    def ctrl_c_at_the_prompt(prompt=""):
        # The main thread's handler sets the cancel after the read ended: 0.3 s is
        # later than the executor needs to report a denial, inside the 0.5 s grace.
        threading.Timer(0.3, cancel.set).start()
        raise EOFError

    monkeypatch.setattr("builtins.input", ctrl_c_at_the_prompt)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    events: list[tuple[str, dict]] = []
    turn_context.bind(cancel, lambda kind, data: events.append((kind, data)))
    try:
        executor = Executor(FakeRouter(FakeAdapter("mock", "x")), project_dir=tmp_path)
        plan = Plan(
            assumption="a",
            confidence=0.9,
            steps=[
                Step(action="write", provider_hint="mock", expected_artifact="a.py")
            ],
        )
        result = executor.execute(
            intent="i", plan=plan, approval_callback=console_approval_callback
        )
    finally:
        turn_context.bind(None)

    assert not result.is_ok()
    assert not (tmp_path / "a.py").exists()
    finished = [d for k, d in events if k == "step.finished"]
    assert all(d["outcome"] != "failed" for d in finished), finished
    # What the session shows: the turn ends interrupted, and the checklist reads skipped.
    from ract.session_events import plan_event_data

    state = PlanState()
    state.observe("plan.proposed", plan_event_data(plan))  # the harness emits it
    for kind, data in events:
        state.observe(kind, data)
    state.observe("turn.finished", {"outcome": "interrupted"})
    assert [item["state"] for item in state.items()] == ["skipped"]
