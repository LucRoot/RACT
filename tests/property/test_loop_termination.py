"""Property tests for formal loop termination T1–T7."""

from __future__ import annotations

from dataclasses import replace

import hypothesis.strategies as st
from hypothesis import given, settings

from ract.core.assumption import Violation
from ract.core.assumption_registry import AssumptionRegistry
from ract.core.loop import (
    Budget,
    LoopState,
    MilestoneReport,
    ProviderTimeoutRecord,
    QualityScore,
    TerminationCause,
    WorkspaceSnapshot,
    check_t1,
    check_t2,
    check_t3,
    check_t4,
    check_t5,
    check_t6,
    check_t7,
    evaluate_termination,
)
from ract.handshake_registry import HandshakeRegistry
from ract.loop_planner import Milestone
from ract.manager import Plan


@st.composite
def _budget(draw):
    return Budget(
        max_iterations=draw(st.integers(min_value=1, max_value=20)),
        wall_time_seconds=draw(st.floats(min_value=0.1, max_value=60.0)),
        step_timeout_seconds=draw(st.floats(min_value=0.1, max_value=30.0)),
    )


@st.composite
def _loop_state(draw, budget: Budget | None = None):
    plan = Plan(assumption="test", confidence=1.0, steps=[])
    workspace = WorkspaceSnapshot(files={}, timestamp=0.0)
    registry = AssumptionRegistry()
    handshakes = HandshakeRegistry(draw(st.text(min_size=1, max_size=20)))
    return LoopState(
        plan=plan,
        workspace=workspace,
        budget=budget if budget is not None else draw(_budget()),
        assumption_registry=registry,
        handshake_registry=handshakes,
        start_time=0.0,
    )


@settings(max_examples=50, deadline=None)
@given(state=_loop_state(), now=st.floats(min_value=0.0, max_value=120.0))
def test_termination_evaluates_without_error(state, now):
    """evaluate_termination is total over all generated states."""
    cause = evaluate_termination(state, now)
    assert cause is None or isinstance(cause, TerminationCause)


@settings(max_examples=30, deadline=None)
@given(state=_loop_state())
def test_always_halts_under_iteration_budget(state):
    """Once iteration reaches max_iterations, T5 fires and the loop halts."""
    state.iteration = state.budget.max_iterations
    cause = evaluate_termination(state, now=0.0)
    assert cause is TerminationCause.BUDGET_EXHAUSTED


@settings(max_examples=30, deadline=None)
@given(state=_loop_state())
def test_always_halts_under_wall_time_budget(state):
    """Once wall time exceeds the budget, T5 fires and the loop halts."""
    cause = evaluate_termination(state, now=state.budget.wall_time_seconds + 1.0)
    assert cause is TerminationCause.BUDGET_EXHAUSTED


def test_t1_complete_reachable():
    """T1: all milestones verified with high confidence terminates as COMPLETE."""
    milestones = [
        Milestone(id="m1", description="first", acceptance="done"),
        Milestone(id="m2", description="second", acceptance="done"),
    ]
    reports = [
        MilestoneReport(milestone_id="m1", status="verified", confidence=1.0),
        MilestoneReport(milestone_id="m2", status="verified", confidence=1.0),
    ]
    assert check_t1(milestones, reports, tau_complete=0.95) is TerminationCause.COMPLETE


def test_t1_incomplete_missing_report():
    """T1 does not fire when a milestone is missing its report."""
    milestones = [Milestone(id="m1", description="first", acceptance="done")]
    assert check_t1(milestones, [], tau_complete=0.95) is None


def test_t2_regression_reachable():
    """T2: two consecutive quality regressions terminates as REGRESSED."""
    history = [
        QualityScore(value=0.9, iteration=1),
        QualityScore(value=0.7, iteration=2),
        QualityScore(value=0.5, iteration=3),
    ]
    assert check_t2(history, delta_regress=0.1) is TerminationCause.REGRESSED


def test_t2_single_regression_does_not_fire():
    """A single regression is not enough to trigger T2."""
    history = [
        QualityScore(value=0.9, iteration=1),
        QualityScore(value=0.5, iteration=2),
    ]
    assert check_t2(history, delta_regress=0.1) is None


def test_t3_provenance_failure_reachable():
    """T3: provenance violation terminates as PROVENANCE_FAILURE."""
    assert check_t3(provenance_ok=False) is TerminationCause.PROVENANCE_FAILURE
    assert check_t3(provenance_ok=True) is None


def test_t4_assumption_burst_reachable():
    """T4: exceeding the violated-assumption threshold terminates as ASSUMPTION_BURST."""
    registry = AssumptionRegistry()
    for text in ("a", "b", "c", "d"):
        assumption = registry.propose(text)
        registry.accept(assumption.id)
        registry.violate(assumption.id, Violation(text="boom"))
    assert check_t4(registry, threshold=3) is TerminationCause.ASSUMPTION_BURST
    assert check_t4(registry, threshold=10) is None


def test_t5_budget_exhausted_reachable():
    """T5: exhausted iteration or wall-time budget terminates as BUDGET_EXHAUSTED."""
    budget = Budget(max_iterations=5, wall_time_seconds=10.0, step_timeout_seconds=1.0)
    assert (
        check_t5(5, budget, start_time=0.0, now=1.0)
        is TerminationCause.BUDGET_EXHAUSTED
    )
    assert (
        check_t5(1, budget, start_time=0.0, now=11.0)
        is TerminationCause.BUDGET_EXHAUSTED
    )
    assert check_t5(1, budget, start_time=0.0, now=1.0) is None


def test_t6_handshake_blocked_reachable(tmp_path):
    """T6: a pending blocking handshake terminates as HANDSHAKE_BLOCKED."""
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "service is live")
    assert check_t6(registry) is TerminationCause.HANDSHAKE_BLOCKED
    registry.update_status("m1", "approved")
    assert check_t6(registry) is None


def test_t7_provider_timeout_reachable():
    """T7: two consecutive provider timeouts terminates as PROVIDER_TIMEOUT."""
    record = ProviderTimeoutRecord(consecutive_timeouts=2)
    assert check_t7(record) is TerminationCause.PROVIDER_TIMEOUT
    record = ProviderTimeoutRecord(consecutive_timeouts=1)
    assert check_t7(record) is None


@settings(max_examples=20, deadline=None)
@given(state=_loop_state())
def test_t1_priority_over_t5(state):
    """When T1 and T5 both apply, T1 fires first (complete before budget)."""
    state = replace(
        state, milestones=[Milestone(id="m1", description="d", acceptance="d")]
    )
    state.milestone_history.append(
        MilestoneReport(milestone_id="m1", status="verified", confidence=1.0)
    )
    state.iteration = state.budget.max_iterations
    cause = evaluate_termination(state, now=0.0)
    assert cause is TerminationCause.COMPLETE


# RACT 0.2.0
