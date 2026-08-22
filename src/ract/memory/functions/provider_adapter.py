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

import hashlib
from typing import Protocol

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.budget import (
    BudgetAccountant,
    BudgetDeclaration,
    BudgetExceededError,
    BudgetInputMaxExceeded,
    BudgetSection,
    WhitespaceTokenEstimator,
)
from ract.memory.events import (
    EventSink,
    NullEventSink,
    emit_budget_exceeded,
    emit_state_budget_capped,
)


# Master spec §Context Composition line 71: "state_context bounded at
# 15% of input budget." The bound is expressed against ``input_target``
# (the aim, per §Budget Declaration), not ``input_max`` — a spec-drift
# guard the module_02 SP prompt asks about explicitly.
STATE_CONTEXT_CAP_FRACTION: float = 0.15


def _state_cap_tokens(declaration: BudgetDeclaration) -> int:
    """Return ``floor(0.15 * declaration.input_target)`` per master spec.

    Uses integer floor division so the cap is a pure function of the
    declaration and a test can assert against a fixed integer. Rejects
    negative or zero ``input_target`` shapes at the declaration boundary
    (``BudgetDeclaration.__post_init__``) — this helper trusts the
    invariant.
    """
    return int(declaration.input_target * STATE_CONTEXT_CAP_FRACTION)


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


def refuse_over_max(
    accountant: BudgetAccountant,
    *,
    sink: EventSink | None = None,
) -> None:
    """Pre-model refuse gate for the ``input_max`` boundary.

    v0.5.1 spec-completeness module_02 (closes Lens 1A CRITICAL A-1).
    Master spec `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` §The Token
    Budget System line 48: "If assembly exceeds max, the harness fails
    the invocation with a bounded-context error." Before this wire-in
    only ``hard_ceiling`` was a hard gate; an invocation whose seated
    total exceeded ``input_max`` but stayed under ``hard_ceiling``
    passed silently.

    Raises :class:`~ract.memory.budget.BudgetInputMaxExceeded` (a
    subclass of :class:`~ract.memory.budget.BudgetExceededError`) when
    the seated total exceeds ``declaration.input_max``. Emits
    ``budget.exceeded`` on the sink before the raise so the trace
    carries the reason with ``boundary="input_max"``.

    Every function MUST invoke this after final assembly and BEFORE
    :func:`refuse_over_ceiling` (input_max <= hard_ceiling by
    invariant, so the stricter gate must fire first). The paired
    check is enforced by the AST grep-gate at
    ``tests/architecture/test_refuse_if_over_max_wired.py``.
    """
    active_sink = sink or NullEventSink()
    if not accountant.over_max():
        return
    section_name, delta = accountant._offending_section(
        accountant.declaration.input_max
    )
    emit_budget_exceeded(
        active_sink,
        {
            "function": accountant.declaration.function,
            "section_name": section_name,
            "delta": delta,
            "boundary": "input_max",
        },
    )
    raise BudgetInputMaxExceeded(
        function_name=accountant.declaration.function,
        budget=accountant.declaration,
        actual_input_tokens=accountant.used(),
        section_name=section_name,
        delta=delta,
    )


def refuse_over_ceiling(
    accountant: BudgetAccountant,
    *,
    sink: EventSink | None = None,
) -> None:
    """Pre-model refuse gate for the ``hard_ceiling`` boundary.

    Raises :class:`~ract.memory.budget.BudgetExceededError` when the
    seated total exceeds ``declaration.hard_ceiling``. Emits
    ``budget.exceeded`` on the sink before the raise so the trace
    carries the reason.

    Every function must invoke this after final assembly and before
    ``provider.send``. The pre-model gate is the load-bearing DoD
    item — no model call can fire under an over-ceiling budget.

    v0.5.1 module_02 note: ``hard_ceiling`` is the catastrophic gate
    (input + output + reasoning). The stricter ``input_max`` gate
    (:func:`refuse_over_max`) MUST fire first — see
    ``tests/architecture/test_refuse_if_over_max_wired.py`` for the
    AST enforcement.
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


def _truncate_to_token_cap(
    content: str,
    cap_tokens: int,
    estimator: WhitespaceTokenEstimator,
) -> tuple[str, int]:
    """Truncate ``content`` from the tail until it fits under ``cap_tokens``.

    Returns ``(truncated_content, dropped_line_count)``. The strategy
    (``truncate_tail``) drops trailing lines one at a time and appends
    a one-line marker so a downstream reader can see the truncation
    happened; the marker itself is counted in the seated size.

    Cap floor: if the marker alone exceeds ``cap_tokens`` the helper
    returns an empty-content result (``dropped_line_count`` set to the
    full line count) so the seated section is 0 tokens.
    """
    if cap_tokens <= 0:
        return "", len(content.splitlines())
    lines = content.splitlines()
    dropped = 0
    while lines:
        marker = (
            f"\n[TRUNCATED: state_context capped at {cap_tokens} tokens; "
            f"{dropped} lines dropped from tail]"
        )
        candidate = "\n".join(lines) + marker
        if estimator.estimate(candidate) <= cap_tokens:
            return candidate, dropped
        lines.pop()
        dropped += 1
    return "", dropped


def seat_state_section(
    accountant: BudgetAccountant,
    *,
    content: str,
    content_hash: str,
    sink: EventSink | None = None,
) -> tuple[BudgetSection, str]:
    """Seat the ``state`` section under the 15%-of-input_target cap.

    v0.5.1 spec-completeness module_02 (closes Lens 1A CRITICAL A-2).
    Master spec `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` §Context
    Composition line 71: "state_context bounded at 15% of input
    budget." The cap is computed against ``input_target`` (the aim per
    §Budget Declaration), NOT ``input_max`` — a spec-drift the SP
    prompt asks about explicitly.

    When the ``content``'s token cost fits under the cap, this helper
    is a pass-through to :func:`seat_prompt_section` with
    ``name="state"``. When ``content`` exceeds the cap, this helper:

    - truncates ``content`` from the tail via :func:`_truncate_to_token_cap`
      (strategy: ``truncate_tail``) — trailing lines drop until the
      remaining content fits under the cap.
    - emits ``state.budget_capped`` on the sink with the cap arithmetic
      and the dropped-line count.
    - seats the truncated content (with a re-computed ``content_hash``
      derived from the truncated bytes so the accountant's audit trail
      references what was actually seated).

    Returns ``(seated_section, effective_content)`` — the caller MUST
    use ``effective_content`` when passing the state section to
    :func:`assemble_prompt` so the prompt the model actually sees
    matches the tokens the accountant recorded. Passing the ORIGINAL
    over-cap content into ``assemble_prompt`` after seating would let
    the model see bytes the accountant never charged for (an audit-
    trail lie).

    The ``content_hash`` argument is the caller-supplied hash of the
    ORIGINAL content; on truncation the seated section carries a
    truncated-derived hash and the ORIGINAL hash ships in the
    emitted event payload's ``requested_hash`` field.
    """
    active_sink = sink or NullEventSink()
    cap_tokens = _state_cap_tokens(accountant.declaration)
    requested_tokens = _ESTIMATOR.estimate(content)
    if requested_tokens <= cap_tokens:
        section = BudgetSection(
            name="state", token_count=requested_tokens, content_hash=content_hash
        )
        accountant.seat(section)
        return section, content
    truncated_content, dropped_line_count = _truncate_to_token_cap(
        content, cap_tokens, _ESTIMATOR
    )
    seated_tokens = _ESTIMATOR.estimate(truncated_content)
    truncated_hash = hashlib.sha256(
        truncated_content.encode("utf-8", errors="replace")
    ).hexdigest()
    emit_state_budget_capped(
        active_sink,
        {
            "function": accountant.declaration.function,
            "cap_tokens": cap_tokens,
            "requested_tokens": requested_tokens,
            "seated_tokens": seated_tokens,
            "dropped_entry_count": dropped_line_count,
            "strategy": "truncate_tail",
            "requested_hash": content_hash,
        },
    )
    section = BudgetSection(
        name="state",
        token_count=seated_tokens,
        content_hash=truncated_hash,
    )
    accountant.seat(section)
    return section, truncated_content


__all__ = [
    "MemoryFunctionProvider",
    "STATE_CONTEXT_CAP_FRACTION",
    "assemble_prompt",
    "refuse_over_ceiling",
    "refuse_over_max",
    "seat_prompt_section",
    "seat_state_section",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
