"""Tests for PlanDiff + diff_plans + diff_manager_plans."""

from __future__ import annotations

from ract.core.plan import (
    CURRENT_SCHEMA_VERSION,
    PlanDiff,
    PlanSchema,
    StepSchema,
    diff_plans,
    diff_manager_plans,
    step_content_digest,
)


def _plan(*steps: StepSchema) -> PlanSchema:
    return PlanSchema(
        schema_version=CURRENT_SCHEMA_VERSION,
        assumption="",
        confidence=1.0,
        steps=list(steps),
    )


def test_diff_added_and_removed_steps() -> None:
    old = _plan(
        StepSchema(step_id="a", action="do a"),
        StepSchema(step_id="b", action="do b"),
    )
    new = _plan(
        StepSchema(step_id="b", action="do b"),
        StepSchema(step_id="c", action="do c"),
    )
    diff = diff_plans(old, new)
    assert diff.added_step_ids == ("c",)
    assert diff.removed_step_ids == ("a",)
    assert diff.modified_step_ids == ()


def test_diff_modified_step_by_content_change() -> None:
    old = _plan(StepSchema(step_id="a", action="do a", provider_hint=""))
    new = _plan(StepSchema(step_id="a", action="do a", provider_hint="openai"))
    diff = diff_plans(old, new)
    assert diff.added_step_ids == ()
    assert diff.removed_step_ids == ()
    assert diff.modified_step_ids == ("a",)


def test_diff_identical_plans_empty() -> None:
    steps = (
        StepSchema(step_id="a", action="do a"),
        StepSchema(step_id="b", action="do b"),
    )
    diff = diff_plans(_plan(*steps), _plan(*steps))
    assert diff.is_empty()
    assert diff == PlanDiff()


def test_diff_reordered_but_identical_plans_are_empty() -> None:
    old = _plan(
        StepSchema(step_id="a", action="do a"),
        StepSchema(step_id="b", action="do b"),
    )
    new = _plan(
        StepSchema(step_id="b", action="do b"),
        StepSchema(step_id="a", action="do a"),
    )
    diff = diff_plans(old, new)
    assert diff.is_empty()


def test_step_content_digest_excludes_step_id() -> None:
    a = StepSchema(step_id="alpha", action="do")
    b = StepSchema(step_id="beta", action="do")
    assert step_content_digest(a) == step_content_digest(b)


def test_diff_manager_plans_content_added() -> None:
    """A brand-new step surfaces as added_step_ids (not modified)."""
    from ract.manager import Plan, Step

    old = Plan(
        assumption="x",
        confidence=1.0,
        steps=[Step(action="a", provider_hint="", expected_artifact="")],
    )
    new = Plan(
        assumption="x",
        confidence=1.0,
        steps=[
            Step(action="a", provider_hint="", expected_artifact=""),
            Step(action="b", provider_hint="", expected_artifact=""),
        ],
    )
    diff = diff_manager_plans(old, new)
    # Content-keyed: added_step_ids is one entry (the "b" step's digest).
    assert len(diff.added_step_ids) == 1
    assert diff.removed_step_ids == ()


def test_diff_manager_plans_content_change_removes_and_adds() -> None:
    """A rewritten step surfaces as removed + added (no persistent identity)."""
    from ract.manager import Plan, Step

    old = Plan(
        assumption="",
        confidence=1.0,
        steps=[Step(action="v1", provider_hint="", expected_artifact="")],
    )
    new = Plan(
        assumption="",
        confidence=1.0,
        steps=[Step(action="v2", provider_hint="", expected_artifact="")],
    )
    diff = diff_manager_plans(old, new)
    # With content-hash keying, the v1 step disappears and v2 appears.
    assert len(diff.removed_step_ids) == 1
    assert len(diff.added_step_ids) == 1
    assert diff.modified_step_ids == ()


def test_diff_manager_plans_reordered_identical_is_empty() -> None:
    """Reordered but identical manager plans produce an empty diff.

    Cluster 2 second-pass fix — the old positional keying flagged this
    as modified, generating false-positive plan.rewritten events.
    """
    from ract.manager import Plan, Step

    a = Step(action="a", provider_hint="", expected_artifact="")
    b = Step(action="b", provider_hint="", expected_artifact="")
    old = Plan(assumption="", confidence=1.0, steps=[a, b])
    new = Plan(assumption="", confidence=1.0, steps=[b, a])
    diff = diff_manager_plans(old, new)
    assert diff.is_empty()


def test_diff_manager_plans_dedups_duplicate_content() -> None:
    """Two identical steps aren't collapsed by content-hash keying."""
    from ract.manager import Plan, Step

    s = Step(action="dup", provider_hint="", expected_artifact="")
    old = Plan(assumption="", confidence=1.0, steps=[s, s])
    new = Plan(assumption="", confidence=1.0, steps=[s])
    diff = diff_manager_plans(old, new)
    # One of the two identical steps was dropped; must show as removed.
    assert len(diff.removed_step_ids) == 1
    assert diff.added_step_ids == ()


# RACT 0.4.1
