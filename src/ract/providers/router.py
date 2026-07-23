# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Provider router for RACT.

Selects the best provider adapter for a task based on capability hints, user
preferences, and explicit scores. Supports fallback chains and lightweight
health checks so a single unreachable provider does not block the loop.
"""

from typing import Any

from ract.capability_registry import CapabilityRegistry
from ract.providers.base import ProviderAdapter
from ract.providers.internal_provider import InternalProvider
from ract.providers.local_http_provider import LocalHttpProvider
from ract.providers.openai_provider import OpenAICompatibleProvider
from ract.rooted import Rooted

# Registry of built-in adapters. Users can register custom adapters at runtime.
_ADAPTER_CLASSES: dict[str, type[ProviderAdapter]] = {
    "openai": OpenAICompatibleProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "local_http": LocalHttpProvider,
    "local": LocalHttpProvider,
    "internal": InternalProvider,
}

# Default capability tags inferred from adapter type when the user does not
# declare any. These are conservative defaults; users should override in config.
_DEFAULT_CAPABILITIES: dict[str, set[str]] = {
    "openai": {"chat", "code", "frontier"},
    "openai_compatible": {"chat", "code"},
    "local_http": {"chat", "code", "fast", "local"},
    "local": {"chat", "code", "fast", "local"},
}


def register_adapter(name: str, cls: type[ProviderAdapter]) -> None:
    """Register a custom provider adapter class under the given name."""
    _ADAPTER_CLASSES[name] = cls


class ProviderRouter:
    """Routes tasks to configured provider adapters with scored selection."""

    def __init__(self, providers: dict[str, dict[str, Any]]) -> None:
        self.providers = providers
        self._adapters: dict[str, ProviderAdapter] = {}
        self._registry = CapabilityRegistry()
        self._build_registry()

    def _build_registry(self) -> None:
        """Register all configured providers in the capability registry."""
        for slot_id, config in self.providers.items():
            adapter_rooted = self.get_adapter(slot_id)
            if not adapter_rooted.is_ok():
                continue
            adapter = adapter_rooted.unwrap()
            capabilities = set(config.get("capabilities", adapter.capabilities()))
            if not capabilities:
                adapter_name = config.get("adapter", "openai")
                capabilities = set(_DEFAULT_CAPABILITIES.get(adapter_name, {"chat"}))
            score_weights = config.get("score_weights", {"default": 1.0})
            self._registry.register(slot_id, adapter, capabilities, score_weights)

    def get_adapter(self, name: str) -> Rooted[ProviderAdapter]:
        """Return a cached or newly created adapter for the named slot."""
        if name in self._adapters:
            return Rooted(
                value=self._adapters[name],
                assumption=f"Provider slot '{name}' is already initialized.",
                confidence=1.0,
                provenance=["router.get_adapter"],
                provider=name,
            )

        config = self.providers.get(name)
        if config is None:
            return Rooted(
                value=None,
                assumption=f"Provider slot '{name}' is configured.",
                confidence=0.0,
                provenance=["router.get_adapter"],
                error=f"Provider slot '{name}' is not configured.",
            )

        adapter_name = config.get("adapter", "openai")
        cls = _ADAPTER_CLASSES.get(adapter_name)
        if cls is None:
            return Rooted(
                value=None,
                assumption=f"Adapter '{adapter_name}' is registered.",
                confidence=0.0,
                provenance=["router.get_adapter"],
                error=f"Unknown provider adapter: {adapter_name}",
            )

        adapter = cls(config)
        self._adapters[name] = adapter
        return Rooted(
            value=adapter,
            assumption=f"Adapter '{adapter_name}' instantiated for slot '{name}'.",
            confidence=1.0,
            provenance=["router.get_adapter"],
            provider=name,
        )

    def select_for_hint(self, hint: str) -> Rooted[ProviderAdapter]:
        """Select the highest-scoring provider that matches the capability hint.

        LR:: Hints are advisory. If no provider advertises the hint, fall back to
        the first configured slot so the work is not blocked.
        """
        if not self._registry._providers:
            # No providers could be registered; fall back to first configured.
            if self.providers:
                first = next(iter(self.providers))
                return self.get_adapter(first).with_step("fallback_first_configured")
            return Rooted(
                value=None,
                assumption="At least one provider is configured.",
                confidence=0.0,
                provenance=["router.select_for_hint"],
                error="No providers are configured.",
            )

        selected = self._registry.select(hint)
        if selected.is_ok():
            # Resolve through get_adapter so runtime adapter replacements are
            # respected (e.g., streaming mocks in tests).
            slot_id = selected.provider
            if slot_id is not None:
                return self.get_adapter(slot_id).with_step(f"registry_select:{slot_id}")
            return selected

        # Fallback: return the first configured provider.
        first = next(iter(self.providers))
        return self.get_adapter(first).with_step("fallback_first_configured")

    def fallback_chain(
        self, hint: str, max_attempts: int = 3
    ) -> list[Rooted[ProviderAdapter]]:
        """Return an ordered list of fallback candidates for a capability hint."""
        if not self._registry._providers:
            if self.providers:
                first = next(iter(self.providers))
                return [self.get_adapter(first)]
            return []
        return self._registry.fallback_chain(hint, max_attempts=max_attempts)

    def health_check(self, slot_id: str) -> Rooted[bool]:
        """Check whether the named provider slot is reachable.

        Adapters that do not implement health_check return True by default so
        that local or simple adapters are not penalized.
        """
        adapter_rooted = self.get_adapter(slot_id)
        if not adapter_rooted.is_ok():
            return Rooted(
                value=False,
                assumption=f"Provider slot '{slot_id}' can be instantiated.",
                confidence=0.0,
                provenance=["router.health_check"],
                error=adapter_rooted.error,
            )
        adapter = adapter_rooted.unwrap()
        error: str | None = None
        try:
            healthy = adapter.health_check()
        except Exception as exc:  # noqa: BLE001
            healthy = False
            error = str(exc)
        return Rooted(
            value=healthy,
            assumption=f"Provider slot '{slot_id}' responds to a health check.",
            confidence=1.0 if healthy else 0.0,
            provenance=["router.health_check", slot_id],
            error=error,
        )


# RACT 0.1.1 - Trust and tooling
