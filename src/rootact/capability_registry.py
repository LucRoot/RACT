from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass, field
from typing import Dict, List, Set

from rootact.rooted import Rooted
from rootact.providers.base import ProviderAdapter


@dataclass
class _ProviderEntry:
    adapter: ProviderAdapter
    capabilities: Set[str]
    score: float


@dataclass
class CapabilityRegistry:
    _providers: Dict[str, _ProviderEntry] = field(default_factory=dict)

    def register(
        self,
        slot_id: str,
        adapter: ProviderAdapter,
        capabilities: Set[str],
        score_weights: Dict[str, float],
    ) -> None:
        score = sum(score_weights.get(cap, 0.0) for cap in capabilities)
        self._providers[slot_id] = _ProviderEntry(
            adapter=adapter, capabilities=set(capabilities), score=score
        )

    def select(
        self,
        hint: str,
        prefer: Set[str] = _ROOT_KNOT,  # type: ignore[assignment]
        exclude: Set[str] = _ROOT_KNOT,  # type: ignore[assignment]
    ) -> Rooted[ProviderAdapter]:
        candidates: List[tuple[float, str, ProviderAdapter]] = []
        for slot_id, entry in self._providers.items():
            if prefer is not _ROOT_KNOT and slot_id not in prefer:
                continue
            if exclude is not _ROOT_KNOT and slot_id in exclude:
                continue
            candidates.append((entry.score, slot_id, entry.adapter))

        if not candidates:
            return Rooted(
                value=None,
                assumption="At least one provider is registered for the requested hint.",
                confidence=0.0,
                provenance=["capability_registry"],
                error="No matching provider found",
                hint=hint,
                provider=None,
            )

        # When no preferred set is supplied, require the hint to match a capability.
        if prefer is _ROOT_KNOT:
            capability_matches = [
                (score, slot_id, adapter)
                for score, slot_id, adapter in candidates
                if hint in self._providers[slot_id].capabilities
            ]
            if capability_matches:
                candidates = capability_matches
            else:
                return Rooted(
                    value=None,
                    assumption=f"A registered provider supports the capability '{hint}'.",
                    confidence=0.0,
                    provenance=["capability_registry"],
                    error=f"No provider supports capability '{hint}'",
                    hint=hint,
                    provider=None,
                )

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_slot_id, best_adapter = candidates[0]
        return Rooted(
            value=best_adapter,
            assumption=f"Provider '{best_slot_id}' has the highest score for capability '{hint}'.",
            confidence=1.0,
            provenance=["capability_registry", best_slot_id],
            hint=hint,
            provider=best_slot_id,
        )

    def fallback_chain(
        self,
        hint: str,
        max_attempts: int = 3,
    ) -> List[Rooted[ProviderAdapter]]:
        ordered = sorted(
            self._providers.items(),
            key=lambda item: item[1].score,
            reverse=True,
        )
        chain: List[Rooted[ProviderAdapter]] = []
        for slot_id, entry in ordered[:max_attempts]:
            chain.append(
                Rooted(
                    value=entry.adapter,
                    assumption=f"Provider '{slot_id}' is a fallback candidate for '{hint}'.",
                    confidence=1.0,
                    provenance=["capability_registry", slot_id],
                    hint=hint,
                    provider=slot_id,
                )
            )
        return chain
