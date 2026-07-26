# Benchmark: RACT loop vs naive baseline

**Dimension:** tokens spent to reach a passing state (lower is better)
**Task:** `refactor-function` (split monolithic `process_order` into testable units)
**Token model:** deterministic mock (PROMPT_TOKENS + EDIT_LINES * TOKENS_PER_LINE) — held constant across both runners so the
only variable is the stop policy.
**Runs per side:** 5 (ceiling: 5 iterations)

## Result

| Runner | Mean tokens to pass | Std dev | Mean iterations | Passed |
|---|---|---|---|---|
| Naive baseline | 4320.0 | 0.0 | 5 | 5/5 |
| **RACT contender** | **864.0** | 0.0 | 1 | 5/5 |

The RACT milestone-driven loop used **80.0%** fewer
tokens on average (3456.0 tokens saved) and
reached the passing state in 1 iteration(s) vs the naive
loop's 5.

## Why this is fair

Both runners apply the **same edit** via the eval harness mock
(`ract.eval.runner._mock_run`) and the **same per-step token cost**
(`PROMPT_TOKENS + EDIT_LINES * TOKENS_PER_LINE`). The only difference is the
stop policy: the naive loop runs a fixed number of iterations; the RACT loop
halts the moment the milestone verifies (mirroring `TerminationCause.COMPLETE`,
T1 in `src/ract/core/loop.py`).

The metric respects each runner's actual semantics: the naive baseline is
charged its **full** iteration budget because it has no completion detection
and never observes the milestone; the contender is charged only until the
milestone verifies. Crediting the baseline with "stop when it happens to pass"
would give it completion detection it does not possess.

## Reproduce

```bash
python evals/benchmarks/refactor-token-usage/report.py
```

The run is deterministic; `report.json` and `report.md` are regenerated in place.

## Caveats

- The token model is a deterministic proxy, not a measurement of a live model.
  It isolates the *termination policy's* effect on token spend, which is the
  claim under test. A live-model variant would replace `step_token_cost()` with
  real usage telemetry; the harness would not change.
- This is one task. A stronger benchmark sweeps multiple tasks; that is queued
  as follow-up work.
