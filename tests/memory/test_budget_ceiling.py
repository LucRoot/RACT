"""Sacred spine test: the budget accountant refuses over-ceiling
invocations BEFORE any model call.

Master spec §The token budget system §Enforcement paragraph:

    On over-ceiling: the accountant refuses the invocation before the
    model call and emits ``budget.exceeded`` to the event trace.

Sacred spine item 3 (master spec §Sacred spine): this test file is the
named anchor. If it goes red, the memory-discipline pipeline stops.
"""

from __future__ import annotations

import pytest

from ract.memory.budget import (
    BudgetAccountant,
    BudgetDeclaration,
    BudgetExceededError,
    BudgetSection,
)
from ract.memory.events import (
    BUDGET_EXCEEDED,
    NullEventSink,
    emit_budget_exceeded,
)


def _declaration() -> BudgetDeclaration:
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


class _RecordingModelClient:
    """Test double that records every invocation.

    The sacred-spine assertion is that a caller who goes through the
    accountant NEVER reaches ``.call`` when the seated total exceeds
    the hard ceiling. After a refuse, ``calls`` MUST remain empty.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, prompt: str) -> str:
        self.calls.append({"prompt": prompt})
        return "model-response"


def _dispatch_through_accountant(
    accountant: BudgetAccountant,
    client: _RecordingModelClient,
    prompt: str,
) -> str:
    """Simulate the module_09 assembly-to-dispatch boundary.

    The one line that MUST land before every model call is
    ``accountant.refuse_if_over_ceiling()``. This helper enforces the
    call site shape so the test proves the accountant is the gate.
    """
    accountant.refuse_if_over_ceiling()
    return client.call(prompt)


def test_over_ceiling_refuses_invocation_before_model_call() -> None:
    """Sacred spine item 3: over-ceiling refuse blocks the model call.

    Seat sections whose sum crosses the hard ceiling, then attempt to
    dispatch through the accountant. The dispatch must raise
    :class:`BudgetExceededError` AND the recording model client's
    ``calls`` list must remain empty — no partial dispatch, no retry,
    no silent downgrade.
    """
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 500))
    accountant.seat(_section("function_contract", 500))
    accountant.seat(_section("retrieved_bundle", 1500))
    accountant.seat(_section("invocation_input", 600))
    assert accountant.used() == 3100
    assert accountant.over_ceiling()

    client = _RecordingModelClient()
    with pytest.raises(BudgetExceededError):
        _dispatch_through_accountant(accountant, client, "assembled prompt")
    assert client.calls == [], (
        "sacred spine violated: model client saw an invocation after "
        "the accountant should have refused"
    )


def test_over_max_raises_budget_exceeded_error_naming_section() -> None:
    """The exception names the offending section.

    Depth Chain diagnostic: without the section name a caller cannot
    tell which slice pushed the accountant over. The exception carries
    ``section_name`` AND the ``delta`` by which the boundary was
    exceeded.
    """
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 500))
    accountant.seat(_section("function_contract", 500))
    # Push total to 2500 which is over input_max (2000) but not
    # ceiling (3000). The offender is 'retrieved_bundle'.
    accountant.seat(_section("retrieved_bundle", 1500))
    assert accountant.over_max()
    assert not accountant.over_ceiling()

    with pytest.raises(BudgetExceededError) as exc_info:
        accountant.refuse_if_over_max()
    err = exc_info.value
    assert err.section_name == "retrieved_bundle"
    assert err.boundary == "input_max"
    # Total 2500 - input_max 2000 = 500 over the boundary.
    assert err.delta == 500
    assert "retrieved_bundle" in str(err)
    assert "input_max" in str(err)


def test_under_ceiling_does_not_raise() -> None:
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 500))
    accountant.seat(_section("retrieved_bundle", 1500))
    # Total = 2000; input_max is exactly at boundary (not over).
    accountant.refuse_if_over_max()
    accountant.refuse_if_over_ceiling()


def test_ceiling_delta_is_measured_against_hard_ceiling() -> None:
    accountant = BudgetAccountant(declaration=_declaration())
    accountant.seat(_section("system_prompt", 500))
    accountant.seat(_section("retrieved_bundle", 2600))
    # Total 3100 - ceiling 3000 = 100 over.
    with pytest.raises(BudgetExceededError) as exc_info:
        accountant.refuse_if_over_ceiling()
    assert exc_info.value.boundary == "hard_ceiling"
    assert exc_info.value.delta == 100
    assert exc_info.value.section_name == "retrieved_bundle"


def test_over_ceiling_emits_budget_exceeded_to_null_sink() -> None:
    """The null-sink emitter records the event with the correct kind.

    Module_09 swaps the null sink for :class:`JsonlEventWriter`; the
    invariant this test locks is that the emitter helper does not
    depend on the closed EventKind vocabulary today (so the module can
    land without bumping the Literal alias in
    ``src/ract/trace/events.py``).
    """
    sink = NullEventSink()
    emit_budget_exceeded(
        sink,
        {
            "function": "edit",
            "section_name": "retrieved_bundle",
            "delta": 100,
            "boundary": "hard_ceiling",
        },
    )
    assert sink.records == [
        (
            BUDGET_EXCEEDED,
            {
                "function": "edit",
                "section_name": "retrieved_bundle",
                "delta": 100,
                "boundary": "hard_ceiling",
            },
        )
    ]
