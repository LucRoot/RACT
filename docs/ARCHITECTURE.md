:warning: This file is project documentation, not part of the source code.

# RACT Architecture

RACT is a model-agnostic, local-first agentic coding tool. It turns operator intent into structured plans, executes those plans through configurable providers, and writes verified artifacts to disk.

## System diagram

```
┌─────────────┐     intent      ┌─────────────┐     plan        ┌───────────┐
│   Operator  │ ───────────────▶ │   Planner   │ ─────────────▶ │  Manager  │
└─────────────┘                  └─────────────┘                └─────┬─────┘
       ▲                                                              │
       │                         ┌─────────────┐                      │
       │      run report         │   Executor  │ ◀────────────────────┘
       │ ◀────────────────────── │ (chokepoint)│
       │                         └──────┬──────┘
       │                                │ writes
       │                         ┌──────┴──────┐
       │                         │  Workspace  │
       │                         │ + Rootknot  │
       │                         │   index     │
       │                         └─────────────┘
```

The planner emits a versioned plan. The manager recurses through steps. The executor is the only component allowed to mutate the workspace. Every written artifact is entered into the Rootknot index.

## Boundaries and contracts

1. **Plan contract.** Every `Plan` carries a schema version, a load-bearing assumption, and an ordered list of steps. The plan validator rejects unknown schema versions and steps with missing required fields.
2. **Provenance contract.** Every written artifact carries a signed `Rootknot` that binds it to its plan step, assumption, generator, and parent artifacts. `verify_workspace` checks RK-1 and RK-2 before each recursion step. The public statement of what a Rootknot attests and how RACT stays independent of private systems lives in [`docs/PROVENANCE.md`](PROVENANCE.md).
3. **Assumption contract.** Every step declares the assumptions it depends on. The `AssumptionRegistry` tracks the lifecycle (`proposed`, `active`, `discharged`, `violated`) and propagates violations through the dependency graph.
4. **Threat-model contract.** Every workspace-mutating action passes through `authorize_action` in `src/ract/core/threat_model.py`. Tier-3 actions are refused by default; tier-2 actions require an operator handshake.
5. **Termination contract.** The recursion loop halts on one of T1–T7, each with a distinct `TerminationCause`: success, regression, provenance violation, assumption cascade, budget exhaustion, handshake block, or provider fault.

## Failure modes and concurrency

RACT is specified by what it refuses to do silently. Every failure has a named
halt cause, checked in a fixed order by `evaluate_termination`
(`src/ract/core/loop.py`): T1 → T7, first match wins.

- **Malformed or unknown-version plan JSON.** `PlanValidator.validate_schema`
  rejects any plan missing `schema_version` or carrying an unknown version
  (`src/ract/plan_validator.py`). A rejected plan never reaches the loop, so no
  artifact is written. If a malformed plan somehow reaches execution, the
  resulting quality drop is caught by T2 (`REGRESSED`); a missing provenance
  binding is caught by T3 (`PROVENANCE_FAILURE`).
- **Provider disagreement or timeout.** The `ProviderRouter` exposes a
  `fallback_chain(hint)` and `FallbackChain.try_endpoints` walks it, returning
  the first successful result (`src/ract/providers/router.py`,
  `src/ract/router_fallback.py`). A single provider failure does not halt the
  loop. Only two *consecutive* step timeouts halt with T7
  (`PROVIDER_TIMEOUT`); if every endpoint in the chain fails, the step fails
  and surfaces through T2 or T7 depending on whether it registers as a
  timeout.
- **Milestone oracle rejects repeatedly.** A milestone that never reaches
  `verified` at confidence ≥ `tau_complete` does not halt on its own. The loop
  keeps iterating until either quality regresses twice (T2 `REGRESSED`), the
  iteration/wall-time budget exhausts (T5 `BUDGET_EXHAUSTED`), or — if the
  operator marks the milestone blocking via a handshake — T6
  (`HANDSHAKE_BLOCKED`). There is no "three strikes" rule; the budget is the
  backstop.
- **Concurrent tool execution.** MCP tools run **serially within a plan step**.
  Workspace writes are serialized through the executor, which is the only
  component permitted to mutate the workspace (see system diagram). There is no
  shared-state concurrency on the write path, so artifact order is deterministic
  and the Rootknot index never sees a torn write.
- **Workspace mutation outside the root.** Every workspace-mutating action
  passes through `authorize_action` / `classify_action`
  (`src/ract/core/threat_model.py`). Tier-3 actions (external shell, publish,
  `rm -rf`) are `REFUSE`d by default; Tier-2 actions (package install, git
  commit, network) `REQUIRE_HANDSHAKE`; Tier-1 writes are
  `ALLOW_WITH_ROOTKNOT` (permitted only if accompanied by a signed Rootknot).
  The loop cannot perform an external or destructive action without an explicit
  operator handshake on record.

## Acceptance suite compiled before loop entry

Termination is a fact about the environment, not a model judgment.

Before the recursion loop enters step one, `IntentCompiler.compile`
(`src/ract/core/compile.py`) turns the operator's intent into a frozen
`AcceptanceSuite` (`src/ract/core/predicate.py`). The suite is a tuple of
`AcceptancePredicate` values, each a concrete `PredicateInvocation`
(pytest selector, mypy target, Hypothesis property, assertion callable,
or artifact requirement) tagged with a `required` flag. The suite is
persisted as canonical JSON to `evals/runs/<run_id>/suite.json` **before**
`LoopState` is returned to the caller (`build_loop_state(..., run_dir=…)`).

T1 (`TerminationCause.COMPLETE`) reads

```
all(p.evaluate(final_snapshot).ok for p in state.suite.predicates if p.required)
```

Evaluators are pure over `(invocation, WorkspaceSnapshot)`; verifiers
that would otherwise mutate state read pre-recorded results from
`WorkspaceSnapshot.metadata`. Live execution against a scratch copy of
the snapshot is deferred to the transactional worktree substrate
(module_02).

Three guardrails keep the compile-before-loop rule intact:

- **`LoopState` requires a suite.** Constructing `LoopState` without one
  raises. The compile-before-loop rule is enforced at the type/dataclass
  level, not by convention.
- **Zero-required-predicate suites are refused.** An empty required set
  would let T1 fire trivially; `LoopState.__post_init__` raises
  `ValueError` naming the intent id.
- **`ProgressOracle` is scheduling only.** It still returns a score, but
  T1 no longer consumes it; the score feeds T2 (regression detection)
  and the `RunReporter` projection only.

`RunReporter.render_acceptance_suite` reads the suite and every
`PredicateResult` from the final snapshot, so a reviewer inspects the
exit condition and what the environment observed without re-running the
tool.

See ADR-0010 for the design rationale and rejected alternatives, and
`docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` §2 (Substrate Layer 1) and §11
signals 1 and 2 for the master-spec source.

## Verification

- Core invariants are exercised by property tests in `tests/property/`.
- The eval harness runs three reproducible tasks under `evals/tasks/` and writes reports to `evals/runs/`.
- Each `evals/tasks/<task>/suite.json` is committed as a fixture; a fresh compile against a task workspace must yield a suite with at least three required predicates (module_01 DoD).
- CI runs lint, type-check, tests, and eval-smoke on every push.

<!-- RACT 0.4.0: Acceptance suite compiled before loop entry (ADR-0010) -->
