# RACT Complexity-Based Provider Router

## Goal
Add an optional, configurable provider router that categorizes work by complexity and routes it across a 3-tier model stack:

1. **Local inference (default, ~95%)** — fast, private, zero cloud cost.
2. **Low-cost cloud inference (~5%)** — for tasks that exceed local capacity or are explicitly tagged.
3. **High-cost frontier fallback** — only when both local and low-cost fail or the task is explicitly flagged as requiring frontier reasoning.

## Scope for this wave
- A `ComplexityRouter` class in `src/rootact/providers/complexity_router.py`.
- A public `score_complexity(intent: str, plan_steps: list[dict]) -> str` function returning `"low"`, `"medium"`, `"high"`, or `"frontier"`.
- Configurable endpoint slots in `rootact.yaml` under `complexity_router:`:
  - `local`, `low_cost_cloud`, `high_cost_fallback`
  - Each slot has `base_url`, `model`, `adapter`, `timeout`, `max_tokens`, `cost_per_1k_tokens` (optional).
- Route selection API: `select_endpoint(complexity: str, health_check: bool = True) -> dict`.
- A CLI verb `ract router select --intent "..." [--plan plan.json]` that prints the chosen endpoint and complexity.
- Unit tests for scoring, route selection, and health-check fallback.

## Non-goals
- No automatic cloud billing or quota management.
- No retraining of complexity scores.
- No GitHub integration.

## Complexity signals
- Intent length and keywords ("refactor", "architecture", "security", "large", "book", etc.).
- Plan step count and estimated token budget.
- Explicit user tag `--complexity frontier`.

## Fallback rules
1. Try the tier matching the complexity score.
2. If health check fails, try the next higher-cost tier.
3. If all tiers fail, return an error with a clear message.

## Integration
- `rootact_runner.run_rootact` may optionally accept `complexity_hint` and use the router.
- Existing `ProviderRouter` remains untouched; `ComplexityRouter` is a higher-level orchestrator.
