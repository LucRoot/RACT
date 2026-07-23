"""Tests for the capability-based provider router."""

from __future__ import annotations


from unittest.mock import MagicMock

from ract.providers.router import ProviderRouter


def _mock_adapter(name: str) -> MagicMock:
    adapter = MagicMock()
    adapter.name = name
    adapter.capabilities.return_value = {"chat"}
    adapter.health_check.return_value = True
    return adapter


def _make_router(configs: dict, adapters: dict | None = None) -> ProviderRouter:
    """Build a router with mocked adapter instantiation."""
    adapters = adapters or {}

    def fake_get_adapter(slot_id: str):
        if slot_id in adapters:
            from ract.rooted import Rooted

            return Rooted(
                value=adapters[slot_id],
                assumption="mock",
                confidence=1.0,
                provenance=["test"],
            )
        return ProviderRouter.get_adapter(router, slot_id)

    router = ProviderRouter(configs)
    router._adapters = adapters
    return router


def test_selects_highest_score_matching_hint():
    low = _mock_adapter("low")
    high = _mock_adapter("high")
    router = _make_router(
        {
            "low": {
                "adapter": "openai",
                "capabilities": ["chat"],
                "score_weights": {"chat": 1.0},
            },
            "high": {
                "adapter": "openai",
                "capabilities": ["chat"],
                "score_weights": {"chat": 5.0},
            },
        },
        {"low": low, "high": high},
    )
    result = router.select_for_hint("chat")
    assert result.is_ok()
    assert result.unwrap() is high


def test_fallback_to_first_configured_when_no_registry_match():
    only = _mock_adapter("only")
    router = _make_router(
        {
            "only": {
                "adapter": "openai",
                "capabilities": ["chat"],
                "score_weights": {"chat": 1.0},
            }
        },
        {"only": only},
    )
    result = router.select_for_hint("code")
    assert result.is_ok()
    assert result.unwrap() is only


def test_empty_provider_list_raises():
    router = ProviderRouter({})
    result = router.select_for_hint("chat")
    assert not result.is_ok()
    assert "No providers are configured" in (result.error or "")


def test_fallback_chain_orders_by_score():
    first = _mock_adapter("first")
    second = _mock_adapter("second")
    router = _make_router(
        {
            "first": {
                "adapter": "openai",
                "capabilities": ["chat"],
                "score_weights": {"chat": 10.0},
            },
            "second": {
                "adapter": "openai",
                "capabilities": ["chat"],
                "score_weights": {"chat": 1.0},
            },
        },
        {"first": first, "second": second},
    )
    chain = router.fallback_chain("chat", max_attempts=2)
    assert [c.provider for c in chain] == ["first", "second"]


def test_health_check_returns_false_when_adapter_cannot_be_created():
    router = ProviderRouter({})
    result = router.health_check("missing")
    assert not result.is_ok()
    assert result.unwrap() is False


# RACT 0.1.1 - Trust and tooling
