"""Run the refactor-token-usage benchmark and emit report.json + report.md.

Compares the RACT milestone-driven loop (contender) against a naive
fixed-iteration loop (baseline) on the dimension: tokens spent to reach a
passing state. Runs both runners, computes mean token usage at the passing
point, reports variance, and writes a Markdown report suitable for committing
and referencing from the README.

Run:
    python evals/benchmarks/refactor-token-usage/report.py

The benchmark is deterministic (mock provider, fixed token model), so variance
across runs is zero by construction; the report still computes and prints it
so the methodology is visible and a future stochastic provider drops in
without changing the harness.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from baseline import NaiveLoopRunner  # noqa: E402
from contender import RACTLoopRunner  # noqa: E402

MAX_ITERATIONS = 5
RUNS = 5
REPORT_DIR = Path(__file__).resolve().parent


def tokens_to_pass(outcomes: list, runner: object) -> float:
    """Tokens each runner actually spends before stopping.

    The two runners have different stopping semantics, and the metric must
    reflect that honestly rather than impose a single definition:

    - The RACT contender stops at the first passing iteration (it has
      completion detection), so its cost is cumulative tokens at that point.
    - The naive baseline has NO completion detection — it never observes the
      milestone, so it spends its full iteration budget regardless of whether
      the task passed early. Its cost is cumulative tokens at the final
      iteration. Charging it only "until it happened to pass" would credit it
      with completion detection it does not have, which is exactly the
      strawman the benchmark exists to avoid.

    Passing the runner in keeps this distinction explicit and auditable.
    """
    from baseline import NaiveLoopRunner  # local to avoid cycle

    if isinstance(runner, NaiveLoopRunner):
        # No completion detection: spend the whole budget.
        return outcomes[-1].tokens_spent if outcomes else 0.0
    # Contender: stop at first pass (or full budget if it never passed).
    for o in outcomes:
        if o.milestone_passed:
            return o.tokens_spent
    return outcomes[-1].tokens_spent if outcomes else 0.0


def reached_pass(outcomes: list) -> bool:
    return any(o.milestone_passed for o in outcomes)


def run_side(name: str, runner, runs: int) -> dict:
    tokens_samples = []
    passed_count = 0
    iterations_samples = []
    for _ in range(runs):
        outcomes = runner.run()
        tokens_samples.append(tokens_to_pass(outcomes, runner))
        iterations_samples.append(len(outcomes))
        if reached_pass(outcomes):
            passed_count += 1
    mean = statistics.mean(tokens_samples)
    stdev = statistics.pstdev(tokens_samples) if len(tokens_samples) > 1 else 0.0
    return {
        "name": name,
        "runs": runs,
        "mean_tokens_to_pass": round(mean, 2),
        "stdev_tokens": round(stdev, 2),
        "min_tokens": round(min(tokens_samples), 2),
        "max_tokens": round(max(tokens_samples), 2),
        "mean_iterations": round(statistics.mean(iterations_samples), 2),
        "passed_runs": passed_count,
    }


def main() -> int:
    baseline = run_side("naive-baseline", NaiveLoopRunner(MAX_ITERATIONS), RUNS)
    contender = run_side("ract-contender", RACTLoopRunner(MAX_ITERATIONS), RUNS)

    delta = baseline["mean_tokens_to_pass"] - contender["mean_tokens_to_pass"]
    pct = (
        round(100.0 * delta / baseline["mean_tokens_to_pass"], 2)
        if baseline["mean_tokens_to_pass"]
        else 0.0
    )
    contender_better = contender["mean_tokens_to_pass"] < baseline["mean_tokens_to_pass"]

    result = {
        "dimension": "tokens spent to reach a passing state (lower is better)",
        "task": "refactor-function",
        "max_iterations_ceiling": MAX_ITERATIONS,
        "runs": RUNS,
        "token_model": "deterministic mock (PROMPT_TOKENS + EDIT_LINES * TOKENS_PER_LINE)",
        "baseline": baseline,
        "contender": contender,
        "contender_mean_delta_vs_baseline": round(delta, 2),
        "contender_pct_fewer_tokens": pct,
        "contender_strictly_better": contender_better,
    }

    json_path = REPORT_DIR / "report.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    md = _markdown(result)
    (REPORT_DIR / "report.md").write_text(md, encoding="utf-8")

    print(json.dumps(result, indent=2))
    print(f"\nReport written to {REPORT_DIR / 'report.md'}")
    return 0 if contender_better else 1


def _markdown(r: dict) -> str:
    b, c = r["baseline"], r["contender"]
    return f"""# Benchmark: RACT loop vs naive baseline

**Dimension:** {r["dimension"]}
**Task:** `{r["task"]}` (split monolithic `process_order` into testable units)
**Token model:** {r["token_model"]} — held constant across both runners so the
only variable is the stop policy.
**Runs per side:** {r["runs"]} (ceiling: {r["max_iterations_ceiling"]} iterations)

## Result

| Runner | Mean tokens to pass | Std dev | Mean iterations | Passed |
|---|---|---|---|---|
| Naive baseline | {b["mean_tokens_to_pass"]} | {b["stdev_tokens"]} | {b["mean_iterations"]} | {b["passed_runs"]}/{b["runs"]} |
| **RACT contender** | **{c["mean_tokens_to_pass"]}** | {c["stdev_tokens"]} | {c["mean_iterations"]} | {c["passed_runs"]}/{c["runs"]} |

The RACT milestone-driven loop used **{r["contender_pct_fewer_tokens"]}%** fewer
tokens on average ({r["contender_mean_delta_vs_baseline"]} tokens saved) and
reached the passing state in {c["mean_iterations"]} iteration(s) vs the naive
loop's {b["mean_iterations"]}.

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
"""


if __name__ == "__main__":
    raise SystemExit(main())

# RACT 0.3.0
