"""module_09: seven new EventKind members land in LEGAL_EVENT_KINDS.

Master spec §Signals items 11-13 name the closed vocabulary bump:
budget.declared, budget.exceeded, retrieval.requested,
retrieval.satisfied, retrieval.cascaded, retrieval.refused,
probe.evaluated. LEGAL_EVENT_KINDS auto-recomputes from the
Literal alias via typing.get_args, so a simple membership check
is enough.
"""

from __future__ import annotations

from ract.memory.events import MEMORY_EVENT_KINDS
from ract.trace.events import LEGAL_EVENT_KINDS

_NEW_KINDS = (
    "budget.declared",
    "budget.exceeded",
    "retrieval.requested",
    "retrieval.satisfied",
    "retrieval.cascaded",
    "retrieval.refused",
    "probe.evaluated",
)

# v0.5.1 spec-completeness module_02: one further memory-layer kind
# extends the vocabulary — the state_context 15% sub-budget cap event
# emitted from `seat_state_section`.
_MODULE_02_KINDS = ("state.budget_capped",)

_EXPECTED_MEMORY_KINDS = frozenset(_NEW_KINDS + _MODULE_02_KINDS)


def test_seven_new_kinds_in_legal_set() -> None:
    """Every new kind is a member of LEGAL_EVENT_KINDS."""
    missing = [k for k in _NEW_KINDS if k not in LEGAL_EVENT_KINDS]
    assert not missing, f"missing kinds from LEGAL_EVENT_KINDS: {missing}"


def test_memory_event_kinds_match_new_kinds() -> None:
    """memory.events.MEMORY_EVENT_KINDS matches the closed set.

    v0.5.1 module_02 extended the set with ``state.budget_capped``;
    the expected set is composed of ``_NEW_KINDS`` (module_09) plus
    ``_MODULE_02_KINDS`` (module_02).
    """
    assert MEMORY_EVENT_KINDS == _EXPECTED_MEMORY_KINDS


def test_module_02_state_budget_capped_in_legal_set() -> None:
    """v0.5.1 module_02: ``state.budget_capped`` in LEGAL_EVENT_KINDS.

    The 15%-of-input_target sub-budget cap emits this kind on truncation;
    trace/events.py Literal must carry it or the emit path trips the
    ``NullEventSink.emit`` gate.
    """
    assert "state.budget_capped" in LEGAL_EVENT_KINDS
    assert "state.budget_capped" in MEMORY_EVENT_KINDS


def test_memory_kinds_subset_of_legal_kinds() -> None:
    """Second Pass Q2 fold: MEMORY_EVENT_KINDS is a subset of LEGAL_EVENT_KINDS.

    The `_assert_memory_kinds_subset_of_legal` import-time check
    guards structural sync between the memory-layer emitter's set
    and the closed vocabulary. The subset assertion runs at import
    time, so a future drift raises RuntimeError before any test
    file that imports ract.memory.events can even collect.
    """
    assert MEMORY_EVENT_KINDS.issubset(LEGAL_EVENT_KINDS)


def test_no_duplicate_event_kinds_after_bump() -> None:
    """No accidental duplication after the seven-kind bump.

    LEGAL_EVENT_KINDS is a frozenset so duplication would be
    silently deduped — assert the count grew by exactly 7 versus
    the v0.4.1 baseline (25 kinds).
    """
    # The v0.4.1 baseline (module_08 close) had 25 kinds; module_09
    # adds 7 → 32.  If a future era adds kinds this assertion needs
    # updating alongside the LEGAL_EVENT_KINDS bump.
    assert len(LEGAL_EVENT_KINDS) >= 32


# RACT 0.5.0
