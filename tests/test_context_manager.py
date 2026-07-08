from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import tempfile

from rootact.context_manager import ContextManager, SessionState
from rootact.manager import Plan, Step


def test_save_and_load_roundtrip():
    base_dir = tempfile.mkdtemp()
    cm = ContextManager(base_dir)
    session_id = "test_session"
    initial_state = SessionState(
        goal="Test Goal",
        constraints={"max_steps": 5},
        plan=Plan(
            assumption="Initial assumption",
            confidence=0.9,
            steps=[Step(action="noop", provider_hint="test", expected_artifact="none")],
        ),
        recent_failures=2,
        artifacts={"key": b"value"},
    )
    cm.save(session_id, initial_state)
    loaded = cm.load(session_id)
    assert loaded.goal == initial_state.goal
    assert loaded.constraints == initial_state.constraints
    assert loaded.plan == initial_state.plan
    assert loaded.recent_failures == initial_state.recent_failures
    assert loaded.artifacts == initial_state.artifacts


def test_clear_removes_artifacts_plan_and_failures():
    base_dir = tempfile.mkdtemp()
    cm = ContextManager(base_dir)
    session_id = "clear_test"
    state = SessionState(
        goal="Some Goal",
        constraints={"limit": 10},
        plan=Plan(
            assumption="plan_assumption",
            confidence=0.5,
            steps=[Step(action="do", provider_hint="test", expected_artifact="out")],
        ),
        recent_failures=3,
        artifacts={"artifact": b"data"},
    )
    cm.save(session_id, state)
    cm.clear(session_id, keep_goal=False)
    cleared = cm.load(session_id)
    assert cleared.goal == ""
    assert cleared.constraints == {}
    assert cleared.plan is None
    assert cleared.recent_failures == 0
    assert cleared.artifacts == {}


def test_clear_preserves_goal_and_constraints():
    base_dir = tempfile.mkdtemp()
    cm = ContextManager(base_dir)
    session_id = "keep_goal_test"
    original_goal = "Preserve This Goal"
    original_constraints = {"api": "v1", "timeout": 30}
    state = SessionState(
        goal=original_goal,
        constraints=original_constraints,
        plan=None,
        recent_failures=5,
        artifacts={"temp": b"file"},
    )
    cm.save(session_id, state)
    cm.clear(session_id, keep_goal=True)
    preserved = cm.load(session_id)
    assert preserved.goal == original_goal
    assert preserved.constraints == original_constraints
    assert preserved.plan is None
    assert preserved.recent_failures == 0
    assert preserved.artifacts == {}


def test_reset_to_goal_replaces_state():
    base_dir = tempfile.mkdtemp()
    cm = ContextManager(base_dir)
    session_id = "reset_test"
    initial_state = SessionState(
        goal="Old Goal",
        constraints={"old": 1},
        plan=Plan(
            assumption="old",
            confidence=0.1,
            steps=[],
        ),
        recent_failures=4,
        artifacts={"old": b"data"},
    )
    cm.save(session_id, initial_state)
    cm.reset_to_goal(session_id, goal="New Goal", constraints={"new": 2})
    updated = cm.load(session_id)
    assert updated.goal == "New Goal"
    assert updated.constraints == {"new": 2}
    assert updated.plan is None
    assert updated.recent_failures == 0
    assert updated.artifacts == {}


def test_rollback_streak_increments_and_saves():
    base_dir = tempfile.mkdtemp()
    cm = ContextManager(base_dir)
    session_id = "streak_test"
    state = SessionState(
        goal="Goal", constraints={}, plan=None, recent_failures=0, artifacts={}
    )
    cm.save(session_id, state)
    streak1 = cm.rollback_streak(session_id)
    assert streak1 == 1
    loaded1 = cm.load(session_id)
    assert loaded1.recent_failures == 1
    streak2 = cm.rollback_streak(session_id)
    assert streak2 == 2
    loaded2 = cm.load(session_id)
    assert loaded2.recent_failures == 2
    final_streak = cm.rollback_streak(session_id)
    assert final_streak == 3
    loaded3 = cm.load(session_id)
    assert loaded3.recent_failures == 3


# RACT 0.1.0 - Initial Public Release
