"""v0.5.1 spec-completeness module_02 — input_max hard-refuse regression.

Closes audit Lens 1A CRITICAL A-1
(``_BUILD/audit_2026-08-21c/lens_1A_budget_system.md`` §CRITICAL-A):

    ``refuse_if_over_max`` implemented at ``budget.py:506-521`` but grep
    across ``src/ract`` returns ZERO call sites. Spec (line 48) makes
    ``input_max`` a hard rejection boundary. Today only ``hard_ceiling``
    is a hard gate — invocations between ``input_max`` and
    ``hard_ceiling`` proceed silently.

The regression proves three things:

1. A seated total in the ``(input_max, hard_ceiling]`` range NOW raises
   :class:`BudgetInputMaxExceeded` (was: silently accepted).
2. A seated total ``<= input_max`` does NOT raise.
3. A seated total ``> hard_ceiling`` still raises the hard-ceiling gate
   (existing behavior preserved; the wire-in doesn't degrade the
   sacred spine).

Additionally:
- :class:`BudgetInputMaxExceeded` subclasses :class:`BudgetExceededError`
  so ``except BudgetExceededError`` still catches (backward compat).
- The exception carries ``function_name``, ``budget``,
  ``actual_input_tokens`` per the operator directive.
- The ``budget.exceeded`` event fires with ``boundary="input_max"``
  before the raise (audit trail carries the reason).
"""

from __future__ import annotations

import pytest

from ract.memory.budget import (
    BudgetAccountant,
    BudgetDeclaration,
    BudgetExceededError,
    BudgetInputMaxExceeded,
    BudgetSection,
)
from ract.memory.events import BUDGET_EXCEEDED, NullEventSink
from ract.memory.functions.provider_adapter import (
    refuse_over_ceiling,
    refuse_over_max,
)


def _declaration() -> BudgetDeclaration:
    """Test declaration with a wide (input_max, hard_ceiling) gap.

    input_max=2000, hard_ceiling=3000: the 1000-token gap is the
    silent-acceptance loophole this test file closes.
    """
    return BudgetDeclaration(
        function="edit",
        input_min=100,
        input_target=1000,
        input_max=2000,
        output_min=100,
        output_target=500,
        output_max=500,
        reasoning_headroom=500,
        hard_ceiling=3000,
    )


def _section(name: str, tokens: int) -> BudgetSection:
    return BudgetSection(name=name, token_count=tokens, content_hash=f"h_{name}")


# ---------------------------------------------------------------------------
# Regression: total in (input_max, hard_ceiling] now hard-refuses
# ---------------------------------------------------------------------------


def test_seated_between_input_max_and_hard_ceiling_now_raises() -> None:
    """A-1 loophole closure: 2500 tokens under (max=2000, ceiling=3000).

    Before module_02 this passed silently — only the ceiling was a
    hard gate. After module_02 ``refuse_over_max`` raises
    :class:`BudgetInputMaxExceeded` and the model call never fires.
    """
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 500))
    accountant.seat(_section("retrieved_bundle", 2000))
    # Total = 2500; over input_max (2000) but under hard_ceiling (3000).
    assert accountant.used() == 2500
    assert accountant.over_max()
    assert not accountant.over_ceiling()

    sink = NullEventSink()
    with pytest.raises(BudgetInputMaxExceeded) as exc_info:
        refuse_over_max(accountant, sink=sink)
    err = exc_info.value
    assert err.function_name == "edit"
    assert err.budget is accountant.declaration
    assert err.actual_input_tokens == 2500
    assert err.section_name == "retrieved_bundle"
    assert err.delta == 500
    assert err.boundary == "input_max"


def test_input_max_hard_refuse_emits_budget_exceeded_event() -> None:
    """The refusal emits ``budget.exceeded`` before the raise.

    Trace consumers see the reason as ``boundary="input_max"`` (the
    stricter gate) rather than the older ``hard_ceiling``-only signal.
    """
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 1000))
    accountant.seat(_section("retrieved_bundle", 1500))
    sink = NullEventSink()
    with pytest.raises(BudgetInputMaxExceeded):
        refuse_over_max(accountant, sink=sink)
    assert sink.records, "budget.exceeded event should have fired"
    kind, payload = sink.records[-1]
    assert kind == BUDGET_EXCEEDED
    assert payload["function"] == "edit"
    assert payload["boundary"] == "input_max"
    assert payload["section_name"] == "retrieved_bundle"
    assert payload["delta"] == 500


# ---------------------------------------------------------------------------
# Under input_max — no refuse
# ---------------------------------------------------------------------------


def test_seated_under_input_max_does_not_raise() -> None:
    """A well-formed invocation still passes both gates.

    Ensures the wire-in did not degrade the happy path.
    """
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 500))
    accountant.seat(_section("retrieved_bundle", 1500))
    # Total = 2000; input_max is exactly at boundary (not over).
    sink = NullEventSink()
    refuse_over_max(accountant, sink=sink)  # no raise
    refuse_over_ceiling(accountant, sink=sink)  # no raise
    assert sink.records == [], "no event should fire when under both gates"


# ---------------------------------------------------------------------------
# Over hard_ceiling — existing ceiling gate still works
# ---------------------------------------------------------------------------


def test_seated_over_hard_ceiling_still_raises_input_max_first() -> None:
    """input_max is stricter; over-ceiling totals trip input_max first.

    Since input_max (2000) < hard_ceiling (3000), a total > ceiling is
    also > input_max. The input_max gate fires FIRST because callers
    invoke it BEFORE refuse_over_ceiling (enforced by the AST grep-gate
    at ``tests/architecture/test_refuse_if_over_max_wired.py``).

    A caller that skipped refuse_over_max would fall through to
    refuse_over_ceiling and get the older BudgetExceededError with
    boundary="hard_ceiling" — but that path is now forbidden by the
    AST gate.
    """
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 500))
    accountant.seat(_section("retrieved_bundle", 2600))
    # Total = 3100; over both.
    assert accountant.over_max()
    assert accountant.over_ceiling()

    with pytest.raises(BudgetInputMaxExceeded) as exc_info:
        refuse_over_max(accountant)
    assert exc_info.value.boundary == "input_max"


def test_ceiling_gate_preserved_when_input_max_skipped() -> None:
    """If a caller reached the ceiling gate directly it still fires.

    Preserves the sacred-spine invariant: over-ceiling ALWAYS refuses
    the invocation. Nothing about the module_02 wire-in weakens the
    catastrophic gate.
    """
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 500))
    accountant.seat(_section("retrieved_bundle", 2600))
    with pytest.raises(BudgetExceededError) as exc_info:
        refuse_over_ceiling(accountant)
    assert exc_info.value.boundary == "hard_ceiling"


# ---------------------------------------------------------------------------
# Subclass compat
# ---------------------------------------------------------------------------


def test_budget_input_max_exceeded_is_budget_exceeded_subclass() -> None:
    """Backward compat: existing ``except BudgetExceededError`` catches.

    The v0.5.0-era sacred-spine sites catch :class:`BudgetExceededError`;
    the new exception must be catchable through that alias so no
    existing catch site turns into a lost error.
    """
    assert issubclass(BudgetInputMaxExceeded, BudgetExceededError)


def test_accountant_refuse_if_over_max_raises_new_subclass_type() -> None:
    """The accountant's own refuse method now raises the subclass.

    Callers who use ``accountant.refuse_if_over_max()`` directly
    (bypassing the provider_adapter wrapper) still get the structured
    variant with ``function_name`` / ``budget`` / ``actual_input_tokens``.
    """
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 1500))
    accountant.seat(_section("retrieved_bundle", 1000))
    with pytest.raises(BudgetInputMaxExceeded) as exc_info:
        accountant.refuse_if_over_max()
    err = exc_info.value
    assert err.function_name == "edit"
    assert err.actual_input_tokens == 2500
    assert isinstance(err, BudgetExceededError)  # subclass invariant


# RACT 0.5.1
