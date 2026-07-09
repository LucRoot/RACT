from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from typing import Any

from rootact.capability_registry import CapabilityRegistry
from rootact.rooted import Rooted
from rootact.providers.base import ProviderAdapter


class FakeAdapter(ProviderAdapter):
    def __init__(self, name: str, score: float) -> None:
        super().__init__({"name": name, "score": score})
        self._name = name
        self._score = score

    @property
    def name(self) -> str:
        return self._name

    def models(self) -> list[str]:
        return ["fake-model"]

    def capabilities(self) -> set[str]:
        return set()

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 512,
        temperature: float = 0.3,
    ) -> Rooted[dict[str, Any]]:
        return Rooted(value={}, assumption="fake", provenance=["fake"])


class TestCapabilityRegistry:
    def test_register_and_select_successful_match(self) -> None:
        registry = CapabilityRegistry()
        adapter_a = FakeAdapter("A", 0.9)
        adapter_b = FakeAdapter("B", 0.7)
        registry.register("slot_a", adapter_a, {"cap1"}, {"cap1": 1.0})
        registry.register("slot_b", adapter_b, {"cap2"}, {"cap2": 1.0})
        result: Rooted[ProviderAdapter] = registry.select("cap1")
        assert result.value is adapter_a
        assert result.error is None
        assert result.provider == "slot_a"

    def test_select_returns_error_when_no_match(self) -> None:
        registry = CapabilityRegistry()
        registry.register("slot_a", FakeAdapter("A", 0.5), {"cap1"}, {"cap1": 1.0})
        result: Rooted[ProviderAdapter] = registry.select("unknown_cap")
        assert result.value is None
        assert "No provider supports" in (result.error or "")
        assert result.hint == "unknown_cap"

    def test_select_respects_prefer_and_exclude(self) -> None:
        registry = CapabilityRegistry()
        adapter_x = FakeAdapter("X", 0.8)
        adapter_y = FakeAdapter("Y", 0.6)
        registry.register("X", adapter_x, {"c1"}, {"c1": 1.0})
        registry.register("Y", adapter_y, {"c2"}, {"c2": 1.0})
        result = registry.select("c1", prefer={"X"}, exclude={"Y"})
        assert result.value is adapter_x
        assert result.provider == "X"

    def test_fallback_chain_returns_providers_in_score_order(self) -> None:
        registry = CapabilityRegistry()
        adapter_1 = FakeAdapter("One", 0.9)
        adapter_2 = FakeAdapter("Two", 0.5)
        adapter_3 = FakeAdapter("Three", 0.3)
        registry.register("One", adapter_1, {"c1"}, {"c1": 1.0})
        registry.register("Two", adapter_2, {"c2"}, {"c2": 1.0})
        registry.register("Three", adapter_3, {"c3"}, {"c3": 1.0})
        chain = registry.fallback_chain("hint", max_attempts=2)
        assert len(chain) == 2
        assert chain[0].provider == "One"
        assert chain[1].provider == "Two"

    def test_fallback_chain_respects_max_attempts(self) -> None:
        registry = CapabilityRegistry()
        for i in range(5):
            registry.register(
                f"slot{i}", FakeAdapter(f"slot{i}", i * 0.1), {"c"}, {"c": 1.0}
            )
        chain = registry.fallback_chain("hint", max_attempts=3)
        assert len(chain) == 3
        assert all(r.error is None for r in chain)

    def test_empty_registry_returns_rooted_error(self) -> None:
        registry = CapabilityRegistry()
        result = registry.select("any_hint")
        assert result.value is None
        assert "No matching provider" in (result.error or "")
        assert result.provider is None
        assert result.hint == "any_hint"

    def test_select_with_defaults_when_none_provided(self) -> None:
        registry = CapabilityRegistry()
        adapter = FakeAdapter("Default", 0.4)
        registry.register("default", adapter, {"c"}, {"c": 1.0})
        result = registry.select("c")
        assert result.value is adapter
        assert result.provider == "default"


# RACT 0.1.1 - Trust and tooling
