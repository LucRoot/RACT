"""Property tests for AssumptionRegistry violation propagation."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from ract.core.assumption import Assumed, AssumptionState, Evidence, Violation
from ract.core.assumption_registry import AssumptionRegistry


@settings(max_examples=30, deadline=None)
@given(chain_length=st.integers(min_value=1, max_value=10))
def test_violating_root_marks_whole_chain_violated(chain_length: int) -> None:
    """Violating the root of a linear dependency chain marks every node violated."""
    registry = AssumptionRegistry()
    from ract.core.types import AssumptionId

    prev_id: AssumptionId | None = None
    ids: list[AssumptionId] = []
    for _ in range(chain_length):
        depends = (prev_id,) if prev_id is not None else ()
        assumption = registry.propose("step assumption", depends)
        registry.accept(assumption.id)
        prev_id = assumption.id
        ids.append(assumption.id)
    violated = registry.violate(ids[0], Violation("root contradiction"))
    assert set(violated) == set(ids)
    for assumption_id in ids:
        loaded = registry.get(assumption_id)
        assert loaded is not None
        assert loaded.state == AssumptionState.VIOLATED


@settings(max_examples=20, deadline=None)
@given(content=st.text(min_size=0, max_size=100))
def test_assumed_becomes_invalid_after_violation(content: str) -> None:
    """An Assumed[T] is invalid once its assumption is violated."""
    registry = AssumptionRegistry()
    assumption = registry.propose("value assumption")
    registry.accept(assumption.id)
    assumed = Assumed(value=content, assumption_id=assumption.id)
    assert assumed.is_valid(registry)
    registry.violate(assumption.id, Violation("contradiction"))
    assert not assumed.is_valid(registry)


def test_discharged_assumption_survives_violation_of_unrelated() -> None:
    """Violating one assumption does not invalidate an unrelated discharged one."""
    registry = AssumptionRegistry()
    a1 = registry.propose("independent")
    registry.accept(a1.id)
    registry.discharge(a1.id, Evidence("test passes"))
    a2 = registry.propose("other")
    registry.accept(a2.id)
    registry.violate(a2.id, Violation("other fails"))
    loaded = registry.get(a1.id)
    assert loaded is not None
    assert loaded.state == AssumptionState.DISCHARGED


# RACT 0.2.0
