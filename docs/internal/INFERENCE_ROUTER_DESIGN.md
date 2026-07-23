# RACT Inference Router — 3-Tier Complexity Design

## Goal

Add an optional RACT module that routes every inference request through a
3-tier stack:

1. **Local primary (95 %)** — self-hosted endpoints on Snapdragon/CPU/NPU.
2. **Low-cost cloud fallback (≈5 %)** — cheap hosted model for local failures
   or tasks the local stack cannot handle.
3. **High-cost frontier fallback** — best-available model for critical failures
   or operator-flagged high-value tasks.

The router must be **configurable, observable, and complexity-aware**.

## Complexity tiers

| Tier | Heuristic | Typical route | Example tasks |
|------|-----------|---------------|---------------|
| `low` | < 200 tokens output, single file, well-scoped | local | renames, JSON exports, simple CLI flags |
| `medium` | 200–1k tokens, multi-file but deterministic | local (larger model) | new module + tests, CLI verb patch |
| `high` | > 1k tokens, reasoning, architecture | local first; cloud on failure | design decisions, spec synthesis |
| `critical` | operator-flagged or repeated local/cloud failure | frontier | regression root-cause, security review |

Complexity is computed from:
- explicit user hint (`--complexity` or task tag)
- output-size estimate from prompt length and requested format
- historical failure rate for similar tasks (from run receipts)
- capability gaps of the local stack (e.g., model does not support vision)

## Provider slots

The router reuses `rootact.providers.router.ProviderRouter`. Each configured
provider gains a `tier` and `cost_rank` field:

```json
{
  "providers": {
    "qwen_local": {
      "adapter": "local_http",
      "url": "http://127.0.0.1:8106/v1/chat/completions",
      "tier": "local",
      "cost_rank": 1,
      "capabilities": ["chat", "code", "local"]
    },
    "openrouter_cheap": {
      "adapter": "openai",
      "url": "https://openrouter.ai/api/v1",
      "tier": "cloud_low_cost",
      "cost_rank": 2,
      "capabilities": ["chat", "code"]
    },
    "openai_frontier": {
      "adapter": "openai",
      "url": "https://api.openai.com/v1",
      "tier": "cloud_high_cost",
      "cost_rank": 3,
      "capabilities": ["chat", "code", "frontier", "reasoning"]
    }
  }
}
```

## Routing algorithm

```python
def route(self, prompt: str, task_context: dict) -> RoutePlan:
    complexity = self._classify_complexity(prompt, task_context)
    chain = self._build_chain(complexity)
    return RoutePlan(complexity=complexity, chain=chain)
```

1. **Classify** the task.
2. **Select ordered candidates** from local → low-cost → high-cost.
3. **Health-check** each candidate; drop unhealthy ones.
4. **Execute** the first healthy candidate.
5. **On failure** (timeout, error, or bad output), retry the next candidate.
6. **Log** the route and outcome to the run receipt.

## Concurrency and thermal integration

The router calls the [REDACTED] thermal endpoint (`:11435/v1/health`) before
allowing concurrent local decode. When the SoC is hot, local requests are
serialized and the router may prefer cloud tiers for non-local-mandatory work.

## CLI / config surface

```bash
rootact run --router-tier local          # force local only
rootact run --router-tier cloud-cheap    # allow low-cost cloud
rootact run --router-tier frontier       # allow frontier fallback
rootact router health                    # show tier health and last route
```

## Open questions

- Should the router be a separate module (`rootact/inference_router.py`) or an
  extension of `providers/router.py`?
- How do we persist per-task complexity labels for learning?
- Do we expose a single `/v1/chat/completions`-compatible proxy so external
  tools ([REDACTED] council, Grove Forge) route through RACT automatically?

## Implementation plan

1. Add `ComplexityClassifier` with heuristics and task-tag overrides.
2. Extend `ProviderRouter` with tier/cost awareness.
3. Add `InferenceRouter` orchestrator that combines classifier + provider
   chain + retry + receipt logging.
4. Add CLI verbs: `router health`, `router route <task>`.
5. Wire thermal check into local-tier concurrency decisions.
