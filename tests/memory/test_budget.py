"""Unit tests for BudgetDeclaration + BudgetAccountant bookkeeping.

Companion tests in ``test_budget_ceiling.py`` cover the sacred-spine
pre-model refuse gate; ``test_budget_narrowing.py`` covers the
narrow-only composition and runtime paths; ``test_budget_registry.py``
covers the YAML defaults loader.
"""

from __future__ import annotations

import pytest

from ract.memory.budget import (
    BudgetAccountant,
    BudgetDeclaration,
    BudgetSection,
    WhitespaceTokenEstimator,
)


def _canonical_declaration() -> BudgetDeclaration:
    """A minimal well-formed declaration used across the tests."""
    return BudgetDeclaration(
        function="unit",
        input_min=100,
        input_target=1000,
        input_max=2000,
        output_min=50,
        output_target=500,
        output_max=500,
        reasoning_headroom=500,
        hard_ceiling=3000,
    )


def _section(name: str, tokens: int) -> BudgetSection:
    return BudgetSection(name=name, token_count=tokens, content_hash=f"h_{name}")


# ---------------------------------------------------------------------------
# BudgetDeclaration.__post_init__ validation
# ---------------------------------------------------------------------------


def test_declaration_accepts_well_formed_shape() -> None:
    decl = _canonical_declaration()
    assert decl.function == "unit"
    assert decl.input_target == 1000
    assert decl.hard_ceiling == 3000


def test_declaration_refuses_input_target_above_input_max() -> None:
    with pytest.raises(ValueError, match="input_target must be <= input_max"):
        BudgetDeclaration(
            function="bad",
            input_min=0,
            input_target=3000,
            input_max=2000,
            output_min=0,
            output_target=100,
            output_max=100,
            reasoning_headroom=100,
            hard_ceiling=10000,
        )


def test_declaration_refuses_output_target_above_output_max() -> None:
    with pytest.raises(ValueError, match="output_target must be <= output_max"):
        BudgetDeclaration(
            function="bad",
            input_min=0,
            input_target=100,
            input_max=200,
            output_min=0,
            output_target=500,
            output_max=200,
            reasoning_headroom=100,
            hard_ceiling=10000,
        )


def test_declaration_refuses_ceiling_below_input_plus_output_plus_headroom() -> None:
    with pytest.raises(
        ValueError, match="hard_ceiling must be >= input_max \\+ output_max"
    ):
        BudgetDeclaration(
            function="bad",
            input_min=0,
            input_target=1000,
            input_max=2000,
            output_min=0,
            output_target=500,
            output_max=1000,
            reasoning_headroom=500,
            hard_ceiling=3000,  # need 2000 + 1000 + 500 = 3500
        )


def test_declaration_refuses_input_min_above_input_target() -> None:
    with pytest.raises(ValueError, match="input_min must be <= input_target"):
        BudgetDeclaration(
            function="bad",
            input_min=500,
            input_target=100,
            input_max=100,
            output_min=0,
            output_target=100,
            output_max=100,
            reasoning_headroom=100,
            hard_ceiling=10000,
        )


def test_declaration_refuses_negative_field() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        BudgetDeclaration(
            function="bad",
            input_min=-1,
            input_target=100,
            input_max=200,
            output_min=0,
            output_target=100,
            output_max=100,
            reasoning_headroom=100,
            hard_ceiling=10000,
        )


def test_declaration_refuses_bool_where_int_expected() -> None:
    # ``True`` is an ``int`` subclass in Python; the declaration must
    # refuse it explicitly so a stray boolean does not pass silently.
    with pytest.raises(TypeError, match="must be int"):
        BudgetDeclaration(
            function="bad",
            input_min=0,
            input_target=True,  # type: ignore[arg-type]
            input_max=200,
            output_min=0,
            output_target=100,
            output_max=100,
            reasoning_headroom=100,
            hard_ceiling=10000,
        )


def test_declaration_refuses_empty_function_name() -> None:
    with pytest.raises(ValueError, match="function must be a non-empty string"):
        BudgetDeclaration(
            function="",
            input_min=0,
            input_target=100,
            input_max=200,
            output_min=0,
            output_target=100,
            output_max=100,
            reasoning_headroom=100,
            hard_ceiling=10000,
        )


def test_declaration_is_frozen() -> None:
    decl = _canonical_declaration()
    with pytest.raises((AttributeError, TypeError)):
        decl.input_max = 9999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BudgetSection value type
# ---------------------------------------------------------------------------


def test_section_carries_name_tokens_and_hash() -> None:
    section = BudgetSection(name="system_prompt", token_count=42, content_hash="abcd")
    assert section.name == "system_prompt"
    assert section.token_count == 42
    assert section.content_hash == "abcd"


def test_section_refuses_empty_name() -> None:
    with pytest.raises(ValueError, match="name must be a non-empty string"):
        BudgetSection(name="", token_count=1, content_hash="h")


def test_section_refuses_negative_token_count() -> None:
    with pytest.raises(ValueError, match="token_count must be a non-negative int"):
        BudgetSection(name="s", token_count=-1, content_hash="h")


def test_section_refuses_empty_hash() -> None:
    with pytest.raises(ValueError, match="content_hash must be a non-empty string"):
        BudgetSection(name="s", token_count=1, content_hash="")


def test_section_is_immutable() -> None:
    section = BudgetSection(name="s", token_count=1, content_hash="h")
    with pytest.raises(TypeError):
        section[0] = "other"  # type: ignore[index]


# ---------------------------------------------------------------------------
# BudgetAccountant.seat + used + remaining + predicates
# ---------------------------------------------------------------------------


def test_accountant_used_is_zero_before_any_seat() -> None:
    accountant = BudgetAccountant(declaration=_canonical_declaration())
    assert accountant.used() == 0
    assert accountant.used("missing") == 0
    assert accountant.remaining() == 1000


def test_accountant_used_sums_seated_sections() -> None:
    accountant = BudgetAccountant(declaration=_canonical_declaration())
    accountant.seat(_section("system_prompt", 200))
    accountant.seat(_section("function_contract", 300))
    accountant.seat(_section("retrieved_bundle", 400))
    assert accountant.used() == 900
    assert accountant.used("system_prompt") == 200
    assert accountant.remaining() == 100


def test_accountant_refuses_double_seat() -> None:
    accountant = BudgetAccountant(declaration=_canonical_declaration())
    accountant.seat(_section("system_prompt", 100))
    with pytest.raises(ValueError, match="already seated"):
        accountant.seat(_section("system_prompt", 200))


def test_accountant_reseat_replaces_prior_seat() -> None:
    accountant = BudgetAccountant(declaration=_canonical_declaration())
    accountant.seat(_section("system_prompt", 100))
    accountant.reseat(_section("system_prompt", 250))
    assert accountant.used("system_prompt") == 250


def test_accountant_reseat_refuses_when_not_yet_seated() -> None:
    accountant = BudgetAccountant(declaration=_canonical_declaration())
    with pytest.raises(ValueError, match="not seated"):
        accountant.reseat(_section("system_prompt", 100))


def test_accountant_over_target_max_ceiling_transitions() -> None:
    accountant = BudgetAccountant(declaration=_canonical_declaration())
    # Under all boundaries.
    accountant.seat(_section("s1", 500))
    assert not accountant.over_target()
    assert not accountant.over_max()
    assert not accountant.over_ceiling()
    # Over target (1000) but not max (2000).
    accountant.seat(_section("s2", 700))
    assert accountant.over_target()
    assert not accountant.over_max()
    assert not accountant.over_ceiling()
    # Over max but not ceiling.
    accountant.seat(_section("s3", 1000))
    assert accountant.over_max()
    assert not accountant.over_ceiling()
    # Over ceiling.
    accountant.seat(_section("s4", 1000))
    assert accountant.over_ceiling()


def test_accountant_sections_returned_in_seat_order() -> None:
    accountant = BudgetAccountant(declaration=_canonical_declaration())
    for name in ("a", "b", "c"):
        accountant.seat(_section(name, 100))
    assert [s.name for s in accountant.sections()] == ["a", "b", "c"]


def test_accountant_run_id_defaults_to_fresh_bytes() -> None:
    left = BudgetAccountant(declaration=_canonical_declaration())
    right = BudgetAccountant(declaration=_canonical_declaration())
    assert len(left._run_id) == 16
    assert len(right._run_id) == 16
    assert left._run_id != right._run_id
    assert left._step_id is None


# ---------------------------------------------------------------------------
# WhitespaceTokenEstimator default
# ---------------------------------------------------------------------------


def test_whitespace_estimator_matches_v0_1_shape() -> None:
    estimator = WhitespaceTokenEstimator()
    assert estimator.estimate("") == 0
    assert estimator.estimate("hello world") == 2
    assert estimator.estimate("one\ttwo\nthree four") == 4
