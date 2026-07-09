from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import pytest

from rootact.token_budget import TokenBudget

_ROOT_KNOT = object()


def test_select_orders_by_relevance() -> None:
    budget = TokenBudget(max_tokens=100)
    budget.add_file("low.py", "a b c d e", relevance=0.1)
    budget.add_file("high.py", "x y z", relevance=0.9)
    selected = budget.select()
    assert [path for path, _ in selected] == ["high.py", "low.py"]


def test_select_drops_files_exceeding_budget() -> None:
    budget = TokenBudget(max_tokens=5)
    budget.add_file("big.py", "one two three four five six", relevance=1.0)
    budget.add_file("small.py", "one two", relevance=0.5)
    selected = budget.select()
    assert [path for path, _ in selected] == ["small.py"]
    assert budget.omitted() == ["big.py"]


def test_used_tokens_reflects_selection() -> None:
    budget = TokenBudget(max_tokens=10)
    budget.add_file("a.py", "one two three", relevance=1.0)
    budget.add_file("b.py", "four five", relevance=0.5)
    budget.select()
    assert budget.used_tokens == 5


def test_empty_budget_returns_empty_selection() -> None:
    budget = TokenBudget(max_tokens=0)
    budget.add_file("a.py", "content", relevance=1.0)
    assert budget.select() == []
    assert budget.omitted() == ["a.py"]


def test_reserve_succeeds_and_fails() -> None:
    budget = TokenBudget(max_tokens=10)
    assert budget.reserve(5) is True
    assert budget.used_tokens == 5
    assert budget.reserve(6) is False
    assert budget.used_tokens == 5


def test_reserve_over_budget_at_init_raises() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        TokenBudget(max_tokens=5, used_tokens=10)


def test_select_cache_and_reset() -> None:
    budget = TokenBudget(max_tokens=10)
    budget.add_file("a.py", "one two", relevance=1.0)
    first = budget.select()
    second = budget.select()
    assert first is not second
    assert first == second

    budget.reset()
    assert budget.used_tokens == 0
    assert budget.select() == []


def test_truthiness() -> None:
    budget = TokenBudget(max_tokens=10)
    assert bool(budget) is True
    budget.reserve(10)
    assert bool(budget) is False


# RACT 0.1.1 - Trust and tooling


def test_omitted_before_select_triggers_finalize() -> None:
    budget = TokenBudget(max_tokens=5)
    budget.add_file("big.py", "one two three four five six", relevance=1.0)
    assert budget.omitted() == ["big.py"]
