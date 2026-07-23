# ADR-0005: Provider Capability Routing

## Status

Accepted

## Context

RACT is model-agnostic: it must work with local models, OpenAI-compatible APIs, and internal adapters. Routing by provider name is brittle: names change, endpoints move, and a single-provider setup creates lock-in. The router must select a provider based on what the current step needs, not on a hardcoded name.

## Decision

Use a capability-based router. Each provider slot advertises a set of capability tags (`chat`, `code`, `fast`, `local`, `frontier`, etc.). The plan step carries a `provider_hint`. `ProviderRouter.select_for_hint(hint)` returns the highest-scoring provider that advertises the hint, with a fallback chain if the first choice fails.

Provider health is checked with a lightweight ping; unhealthy providers are skipped during selection. Scores can be weighted per slot in configuration so operators can prefer cheaper or faster providers for specific capabilities.

## Consequences

- Plans do not depend on provider names or endpoints.
- New providers are registered by capability, not by special-casing the router.
- Fallback chains keep the loop alive when a provider is unreachable.
- Provider health decay is tracked per slot; future work will incorporate latency/error-rate history into scoring.

## Alternatives Considered

- **Single-provider lock-in:** rejected. It would make RACT unusable when that provider is down or unsuitable for a task.
- **Naive round-robin:** rejected. It ignores capability differences and wastes fast providers on simple tasks.
- **Operator-per-step selection:** rejected. It adds friction to every plan and defeats the purpose of an autonomous loop.

## References

- `src/rootact/providers/router.py`
- `src/rootact/capability_registry.py`
