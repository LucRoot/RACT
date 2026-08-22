"""v0.5.1 spec-completeness module_02 — 15% state_context cap regression.

Closes audit Lens 1A CRITICAL A-2
(``_BUILD/audit_2026-08-21c/lens_1A_budget_system.md`` §CRITICAL-B):

    ``state_context`` 15% cap: NOT ENFORCED. Spec (line 71):
    "state_context bounded at 15% of input budget." Grep across the
    repo returns zero hits for any 15%, 0.15, or state-cap computation.
    ``budget.py:462-471`` acknowledges deferral in a comment: *"sub-
    section budgets (the 15 percent state cap in the master spec
    §Context composition) are computed by the caller in module_09's
    assembly pipeline"* — module_09 shipped, cap did not.

The regression proves:

- Over-cap state IS capped to ``floor(0.15 * input_target)`` (was:
  unbounded).
- Under-cap state passes through unchanged.
- The cap uses ``input_target`` (the aim), NOT ``input_max`` — the
  operator-mandated SP question guards this drift.
- Truncation emits ``state.budget_capped`` with the required payload
  fields; the seated section carries a hash of the truncated content
  (not the original) so the audit trail matches what the model saw.
"""

from __future__ import annotations

import hashlib

import pytest

from ract.memory.budget import BudgetAccountant, BudgetDeclaration
from ract.memory.events import NullEventSink
from ract.memory.functions.provider_adapter import (
    STATE_CONTEXT_CAP_FRACTION,
    _state_cap_tokens,
    seat_state_section,
)


def _declaration(
    input_target: int = 1000,
    input_max: int = 5000,
    hard_ceiling: int = 10000,
) -> BudgetDeclaration:
    """Test declaration with a WIDE gap between input_target and input_max.

    The gap proves the cap uses input_target (not input_max): a state
    block sized between ``0.15 * input_target`` and ``0.15 * input_max``
    MUST be capped.
    """
    return BudgetDeclaration(
        function="edit",
        input_min=100,
        input_target=input_target,
        input_max=input_max,
        output_min=100,
        output_target=500,
        output_max=500,
        reasoning_headroom=500,
        hard_ceiling=hard_ceiling,
    )


def _sentence(word_count: int) -> str:
    """Return ``word_count`` newline-separated words for deterministic sizing."""
    return "\n".join(f"word{i}" for i in range(word_count))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Cap arithmetic
# ---------------------------------------------------------------------------


def test_state_cap_uses_input_target_not_input_max() -> None:
    """A-2 spec-drift guard: cap is against ``input_target``.

    Master spec §Budget Declaration: ``target`` is the aim; ``max`` is
    the hard boundary. The 15% cap applies to the aim.
    """
    decl = _declaration(input_target=1000, input_max=5000)
    assert _state_cap_tokens(decl) == 150  # floor(0.15 * 1000)
    assert _state_cap_tokens(decl) != int(decl.input_max * 0.15)  # 750
    assert STATE_CONTEXT_CAP_FRACTION == 0.15


def test_state_cap_is_floor_of_fraction() -> None:
    """Integer floor arithmetic — a test asserts against a fixed value.

    Each declaration passes ``input_max`` >= ``input_target`` per the
    ``BudgetDeclaration.__post_init__`` invariant.
    """
    assert (
        _state_cap_tokens(_declaration(input_target=2000, input_max=5000)) == 300
    )
    assert (
        _state_cap_tokens(_declaration(input_target=3000, input_max=5000)) == 450
    )
    assert (
        _state_cap_tokens(_declaration(input_target=4000, input_max=5000)) == 600
    )
    assert (
        _state_cap_tokens(_declaration(input_target=8000, input_max=9000, hard_ceiling=15000))
        == 1200
    )
    # Non-multiple: floor()
    assert (
        _state_cap_tokens(_declaration(input_target=1007, input_max=5000)) == 151
    )


# ---------------------------------------------------------------------------
# Under-cap: pass-through
# ---------------------------------------------------------------------------


def test_under_cap_state_content_passes_unchanged() -> None:
    """State below cap seats as-is; no event fires; effective == original."""
    decl = _declaration(input_target=1000)  # cap = 150 tokens
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()

    content = _sentence(50)  # 50 tokens, well under cap
    original_hash = _hash(content)

    section, effective = seat_state_section(
        accountant, content=content, content_hash=original_hash, sink=sink
    )
    assert effective == content
    assert section.token_count == 50
    assert section.content_hash == original_hash
    assert sink.records == []  # NO event on pass-through


# ---------------------------------------------------------------------------
# Over-cap: truncation + event
# ---------------------------------------------------------------------------


def test_over_cap_state_content_truncates_to_cap() -> None:
    """State above cap is truncated so seated tokens <= cap."""
    decl = _declaration(input_target=1000)  # cap = 150 tokens
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()

    content = _sentence(500)  # 500 tokens, way over 150 cap
    original_hash = _hash(content)

    section, effective = seat_state_section(
        accountant, content=content, content_hash=original_hash, sink=sink
    )
    assert section.token_count <= 150
    assert len(effective.split()) <= 150
    assert effective != content  # was actually truncated
    assert section.content_hash != original_hash  # hash reflects truncated bytes
    assert "[TRUNCATED" in effective


def test_over_cap_emits_state_budget_capped_event() -> None:
    """The truncation emits ``state.budget_capped`` with full payload."""
    decl = _declaration(input_target=2000)  # cap = 300 tokens
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()

    content = _sentence(500)
    original_hash = _hash(content)

    seat_state_section(
        accountant, content=content, content_hash=original_hash, sink=sink
    )
    assert len(sink.records) == 1
    kind, payload = sink.records[0]
    assert kind == "state.budget_capped"
    assert payload["function"] == "edit"
    assert payload["cap_tokens"] == 300
    assert payload["requested_tokens"] == 500
    assert payload["seated_tokens"] <= 300
    assert payload["dropped_entry_count"] > 0
    assert payload["strategy"] == "truncate_tail"
    assert payload["requested_hash"] == original_hash


def test_over_cap_dropped_entry_count_matches_line_count_delta() -> None:
    """The dropped_entry_count matches the truncation walk's line drops."""
    decl = _declaration(input_target=1000)  # cap = 150
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()

    content = _sentence(400)  # 400 lines
    seat_state_section(
        accountant, content=content, content_hash=_hash(content), sink=sink
    )
    payload = sink.records[0][1]
    # We dropped from 400 lines down to something fitting under 150-ish tokens.
    # The delta is at least 400 - 150 = 250 (rough lower bound).
    assert payload["dropped_entry_count"] >= 250
    assert payload["dropped_entry_count"] < 400  # some content remains


# ---------------------------------------------------------------------------
# Cap uses input_target - direct proof
# ---------------------------------------------------------------------------


def test_cap_ignores_input_max_even_when_wide() -> None:
    """SP-flagged drift: a state block that fits under 15% of input_max
    but NOT under 15% of input_target MUST still be capped.

    Declaration with input_target=1000, input_max=5000:
    - 15% of input_max = 750 tokens (would allow)
    - 15% of input_target = 150 tokens (must cap)
    A 400-token state block SITS BETWEEN — the spec says CAP.
    """
    decl = _declaration(input_target=1000, input_max=5000)  # cap = 150
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()

    content = _sentence(400)  # over 150 (target cap), under 750 (max cap)
    section, _ = seat_state_section(
        accountant, content=content, content_hash=_hash(content), sink=sink
    )
    assert section.token_count <= 150, (
        "cap must be against input_target (150), not input_max (750)"
    )
    assert sink.records, "must have emitted state.budget_capped"


# ---------------------------------------------------------------------------
# Boundary: content exactly at cap
# ---------------------------------------------------------------------------


def test_state_content_exactly_at_cap_does_not_truncate() -> None:
    """Content at the cap boundary passes through (uses <=, not <)."""
    decl = _declaration(input_target=1000)  # cap = 150
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()

    content = _sentence(150)  # exactly 150 tokens
    section, effective = seat_state_section(
        accountant, content=content, content_hash=_hash(content), sink=sink
    )
    assert section.token_count == 150
    assert effective == content
    assert sink.records == []


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


def test_empty_state_content_seats_zero_tokens() -> None:
    """Empty state seats a 0-token section with no event."""
    decl = _declaration(input_target=1000)
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()

    section, effective = seat_state_section(
        accountant, content="", content_hash=_hash(""), sink=sink
    )
    assert section.token_count == 0
    assert effective == ""
    assert sink.records == []


# ---------------------------------------------------------------------------
# Section shape after truncation
# ---------------------------------------------------------------------------


def test_seated_hash_matches_truncated_bytes_not_original() -> None:
    """Audit trail rule: seated hash must reflect what was actually seated.

    A downstream reader who recomputes ``sha256(effective_content)``
    must match ``section.content_hash``. This closes the audit-trail
    lie hazard where the accountant might record an ORIGINAL hash but
    seat truncated bytes.
    """
    decl = _declaration(input_target=1000)
    accountant = BudgetAccountant(declaration=decl)
    sink = NullEventSink()

    content = _sentence(500)
    section, effective = seat_state_section(
        accountant, content=content, content_hash=_hash(content), sink=sink
    )
    assert section.content_hash == _hash(effective)


# ---------------------------------------------------------------------------
# Cross-function coverage (all 4 shipped functions)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "function,input_target,expected_cap",
    [
        ("intake", 2000, 300),
        ("research", 3000, 450),
        ("plan", 4000, 600),
        ("edit", 8000, 1200),
    ],
)
def test_cap_computed_correctly_for_each_shipped_function(
    function: str, input_target: int, expected_cap: int
) -> None:
    """Verify each of the 4 shipped functions gets the correct cap.

    Loops the ``budget_defaults.yaml`` per-function ``input.target``
    values through ``_state_cap_tokens`` — a numeric ground-truth for
    the 15% arithmetic.
    """
    decl = BudgetDeclaration(
        function=function,
        input_min=100,
        input_target=input_target,
        input_max=input_target + 1000,
        output_min=100,
        output_target=500,
        output_max=500,
        reasoning_headroom=500,
        hard_ceiling=input_target + 1000 + 500 + 500,
    )
    assert _state_cap_tokens(decl) == expected_cap


# RACT 0.5.1
