"""Provider adapter for the four v0.5.0 memory-discipline functions.

Lateral Chain branch A (module_06 PRE): the existing ``providers/``
layer at :mod:`ract.providers` speaks a chat-completion protocol
(``ProviderAdapter.complete(messages, ...)``); the four memory-
discipline functions want a simpler surface — one prompt in, one
text-blob out — plus a shared budget-declaration seat check before
any model call.

This module lands:

- :class:`MemoryFunctionProvider` protocol — the ``send(prompt,
  declaration) -> str`` shape every function invokes.
- :func:`assemble_prompt` — the five-section composer per master spec
  §Context composition (system + contract + state + bundle + input).
- :func:`refuse_over_ceiling` — the pre-model refuse gate. Every
  function calls this after assembly and before ``provider.send``.

The adapter is transport-agnostic — it does not know whether the
downstream ``send`` invokes an HTTP client, a local subprocess, or
a canned-response fixture. Module_09 wires the real adapter that
bridges from :class:`MemoryFunctionProvider` to
:class:`ract.providers.base.ProviderAdapter.complete`; until then,
tests use :class:`~ract.memory.functions.testing.mock_provider.MockProvider`.
"""

from __future__ import annotations

from typing import Protocol

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import (
    BudgetAccountant,
    BudgetDeclaration,
    BudgetExceededError,
    BudgetSection,
    WhitespaceTokenEstimator,
)
from ract.memory.events import EventSink, NullEventSink, emit_budget_exceeded


class MemoryFunctionProvider(Protocol):
    """The simplified provider shape the four functions call.

    A conforming implementation returns a plain string; the caller
    parses it against the function-specific JSON contract in the
    matching prompt file.
    """

    def send(self, prompt: str, declaration: BudgetDeclaration) -> str: ...


_ESTIMATOR = WhitespaceTokenEstimator()


def assemble_prompt(
    *,
    system: str,
    contract: str,
    state: str,
    bundle: str,
    inputs: str,
) -> str:
    """Compose the five-section prompt per master spec §Context composition.

    Sections are joined by two newlines with a section-name header so
    the model reads a stable structure across every function. The
    order is fixed:

    1. system — task-independent role framing.
    2. contract — the function's input / output shape.
    3. state — persistent session context (WorkOrder, ResearchBundle).
    4. bundle — the retrieval bundle assembled by the function.
    5. inputs — the current invocation's inputs.
    """
    return (
        "## System\n" + system.strip() + "\n\n"
        "## Contract\n" + contract.strip() + "\n\n"
        "## State\n" + state.strip() + "\n\n"
        "## Bundle\n" + bundle.strip() + "\n\n"
        "## Inputs\n" + inputs.strip() + "\n"
    )


def seat_prompt_section(
    accountant: BudgetAccountant,
    *,
    name: str,
    content: str,
    content_hash: str,
) -> BudgetSection:
    """Seat one section on ``accountant``.

    Returns the seated :class:`BudgetSection` so the caller can record
    it inside the function's audit trail. The section's token cost
    comes from the shipped whitespace estimator; a provider adapter
    with a native tokenizer computes its own count and reseats.
    """
    tokens = _ESTIMATOR.estimate(content)
    section = BudgetSection(name=name, token_count=tokens, content_hash=content_hash)
    accountant.seat(section)
    return section


def refuse_over_ceiling(
    accountant: BudgetAccountant,
    *,
    sink: EventSink | None = None,
) -> None:
    """Pre-model refuse gate.

    Raises :class:`~ract.memory.budget.BudgetExceededError` when the
    seated total exceeds ``declaration.hard_ceiling``. Emits
    ``budget.exceeded`` on the sink before the raise so the trace
    carries the reason.

    Every function must invoke this after final assembly and before
    ``provider.send``. The pre-model gate is the load-bearing DoD
    item — no model call can fire under an over-ceiling budget.
    """
    active_sink = sink or NullEventSink()
    if not accountant.over_ceiling():
        return
    section_name, delta = accountant._offending_section(
        accountant.declaration.hard_ceiling
    )
    emit_budget_exceeded(
        active_sink,
        {
            "function": accountant.declaration.function,
            "section_name": section_name,
            "delta": delta,
            "boundary": "hard_ceiling",
        },
    )
    raise BudgetExceededError(
        declaration=accountant.declaration,
        section_name=section_name,
        delta=delta,
        boundary="hard_ceiling",
    )


__all__ = [
    "MemoryFunctionProvider",
    "assemble_prompt",
    "refuse_over_ceiling",
    "seat_prompt_section",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
