# ADR-0003: Milestone-Driven Recursion with T1–T7 Termination

## Status

Accepted

## Context

RACT v0.1.x ran a fixed-iteration loop capped by `max_iterations`. The loop decided whether to continue, retry, or stop with a loose collection of heuristics: test pass/fail, quality score regression, intent oscillation, refactor-tax thresholds, and the `_ROOT_KNOT` sentinel. Each heuristic was useful, but none were composable or formally tied to a definition of done. The system could churn indefinitely inside the iteration cap, stop early for the wrong reason, or emit a "done" decision with unverified milestones still open.

A claim-and-verify architecture needs a contract that says:

- the loop terminates for a named, auditable reason,
- every reason maps to a verifiable predicate over loop state,
- completion means the plan's milestones are verified, not merely that time ran out.

## Decision

Model the recursion loop as a state machine whose termination is decided by seven pure predicates, T1–T7, evaluated in order on every step.

| Cause | Predicate | Meaning |
|-------|-----------|---------|
| T1 | `check_t1` | All milestones verified with confidence ≥ `tau_complete`. |
| T2 | `check_t2` | Quality regressed by > `delta_regress` for two consecutive iterations. |
| T3 | `check_t3` | Provenance invariant RK-1 or RK-2 is violated. |
| T4 | `check_t4` | More than `assumption_burst_threshold` assumptions violated in one iteration. |
| T5 | `check_t5` | Iteration or wall-time budget exhausted. |
| T6 | `check_t6` | An unresolved blocking handshake is on the critical path. |
| T7 | `check_t7` | Provider step timeout occurred twice consecutively. |

The loop state (`LoopState`) is the single source of truth for a recursion step. It carries the plan, workspace snapshot, milestone history, assumption registry, quality history, iteration counter, budget, handshake registry, provenance flag, and provider timeout record. All predicates are pure functions of this state and the current time.

The `ProgressOracle` now returns a composite score:

- `coverage = verified_milestones / total_milestones`
- `health = 1 - violated_assumptions / max(1, active_assumptions)`
- `consistency = 1` if RK-1 and RK-2 hold, else `0`
- `score = min(coverage, health) * consistency`

The score is always accompanied by a natural-language justification naming the weakest axis, so operators can see why the loop is stuck.

The `MilestoneOracle` supports four verifier categories:

1. **Test-based** — a pytest selector must pass.
2. **Assertion-based** — a callable `(WorkspaceSnapshot) -> bool` evaluates the workspace.
3. **Artifact-based** — the expected file exists and carries a Rootknot signed by the current session.
4. **Provider-based** — a structured judge prompt with a fixed rubric; evals use a deterministic judge so results reproduce.

If no verifier category is specified, the legacy heuristic verifier remains the default, preserving backward compatibility through v0.2.0.

`run_reporter.py` now emits the exact `termination_cause` and the score trajectory across iterations.

## Consequences

- Termination is explicit and auditable: every stop decision names a cause.
- The loop halts under any bounded budget because T5 is a hard ceiling.
- Progress is measured against milestones and assumptions, not just model confidence.
- Provider-based judges must use a fixed seed/rubric; otherwise eval reproducibility is lost.
- Handshakes default to non-blocking; only handshakes explicitly marked blocking can trigger T6.

## Alternatives Considered

- **Time-based looping alone**: simple but cannot distinguish done from timeout.
- **Fixed-iteration caps without predicates**: stops churn but ignores completion evidence.
- **Scalar reward models**: collapses multi-dimensional quality into one number, hiding the weakest axis and making debugging harder.

## References

- `src/ract/core/loop.py`
- `src/ract/progress_oracle.py`
- `src/ract/milestone_oracle.py`
- `src/ract/run_reporter.py`
- `tests/property/test_loop_termination.py`
