"""Tests for the capability-based provider registry."""

from __future__ import annotations


from unittest.mock import MagicMock

from ract.capability_registry import CapabilityRegistry


def _adapter(name: str) -> MagicMock:
    adapter = MagicMock()
    adapter.name = name
    return adapter


def test_select_highest_score_matching_hint():
    registry = CapabilityRegistry()
    low = _adapter("low")
    high = _adapter("high")
    registry.register("low", low, {"chat"}, {"chat": 1.0})
    registry.register("high", high, {"chat"}, {"chat": 5.0})
    result = registry.select("chat")
    assert result.is_ok()
    assert result.unwrap() is high


def test_select_no_match_returns_error():
    registry = CapabilityRegistry()
    adapter = _adapter("only")
    registry.register("only", adapter, {"chat"}, {"chat": 1.0})
    result = registry.select("code")
    assert not result.is_ok()
    assert "No provider supports capability 'code'" in (result.error or "")


def test_fallback_chain_orders_by_score():
    registry = CapabilityRegistry()
    first = _adapter("first")
    second = _adapter("second")
    registry.register("first", first, {"chat"}, {"chat": 10.0})
    registry.register("second", second, {"chat"}, {"chat": 1.0})
    chain = registry.fallback_chain("chat", max_attempts=2)
    assert [c.provider for c in chain] == ["first", "second"]


def test_prefer_set_limits_candidates():
    registry = CapabilityRegistry()
    a = _adapter("a")
    b = _adapter("b")
    registry.register("a", a, {"chat"}, {"chat": 1.0})
    registry.register("b", b, {"chat"}, {"chat": 10.0})
    result = registry.select("chat", prefer={"a"})
    assert result.is_ok()
    assert result.unwrap() is a


# RACT 0.1.1 - Trust and tooling
