# ADR-0002: Assumption Registry with Violation Propagation

## Status

Accepted

## Context

v0.1.x exposed `Rooted[T]` as a wrapper carrying an assumption string and a confidence score. The wrapper made assumptions explicit, but it had no lifecycle: there was no way to discharge an assumption, no way to record evidence, and no way to propagate the effects of a violated assumption to dependent work. The README called this a "signature quirk"; architects expect a contract.

We needed:

- a registry that tracks each assumption from proposal through discharge or violation,
- dependency edges between assumptions so a violation cascades to dependents,
- a typed wrapper `Assumed[T]` whose validity is checked against the registry,
- enough metadata to support targeted re-planning instead of restarting the loop.

## Decision

Replace `Rooted[T]` with `Assumed[T]` and introduce an `AssumptionRegistry`.

Assumptions have four states:

- **PROPOSED** — emitted by the planner.
- **ACTIVE** — accepted by `PlanValidator` as load-bearing.
- **DISCHARGED** — satisfied by evidence produced by the executor.
- **VIOLATED** — contradicted by downstream evidence.

The registry stores `Assumption` objects keyed by 16-byte UUID. `violate(id, violation)` walks the transitive closure of `depends_on` and marks every dependent `VIOLATED`. `invalid_assumed(assumed_items)` returns every `Assumed[T]` whose assumption is no longer active or discharged.

`Assumed[T]` keeps the same ergonomic shape as the old `Rooted[T]` but delegates validity to the registry. The old `Rooted[T]` name remains a deprecated alias through v0.2.0.

## Worked Example

Consider nine plan steps. Step 3 assumes "the login endpoint uses form encoding." Step 5 depends on step 3. Step 7 depends on step 5. When step 8 produces a test showing the endpoint actually expects JSON, the registry marks the step-3 assumption `VIOLATED`, propagates to steps 5 and 7, and the loop re-plans only steps 3-9 instead of restarting from step 1.

## Consequences

- The loop can react to contradictions with a bounded, targeted re-plan.
- Every `Assumed[T]` value carries an audit trail back to its assumption and evidence.
- `PlanValidator` must reject cyclic assumption dependencies.

## Alternatives Considered

- **Design-by-contract preconditions:** too heavy for LLM-authored code; the assumptions are discovered, not declared up front.
- **Pure logging:** no propagation semantics; violations would be buried in output.

## References

- `src/ract/core/assumption.py`
- `src/ract/core/assumption_registry.py`
- `tests/property/test_assumption_propagation.py`
