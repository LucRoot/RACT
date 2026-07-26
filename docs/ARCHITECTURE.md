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

## Transactional execution: worktree-per-step

Every step in the v0.4 loop opens a `StepTransaction`
(`src/ract/core/transaction.py`). The workspace is the durable artifact;
the plan reduces to a schedule over transactions.

- **Code isolation** — a `git worktree` on a step-specific branch named
  `rootact/step/<step_id_hex>`, created off the loop's current parent
  snapshot. `git branch --list "rootact/step/*"` enumerates the active
  transactions, and `ract session ls` presents that listing (with
  `--json` for machine consumption). See `src/ract/executor/worktree.py`.
- **Runtime isolation** — optional per plan step. The
  `ContainerBackend` protocol in `src/ract/executor/runtime.py` ships
  with a `DaggerBackend` and a `PodmanBackend` (`docker` fallback). A
  step whose `runtime_image` is `None` runs in the worktree alone;
  module_03 will land the OS-enforced sandbox inside the container
  the shim starts.
- **Handshake-blocks-commit** — a step whose `handshake_ids` include any
  pending id returns `TransactionOutcome.BLOCKED_ON_HANDSHAKE`; the
  worktree stays intact for operator inspection, the parent-snapshot
  pointer does not advance, and dependent steps cannot commit past the
  blocked one. This is the git-layer replacement for v0.3's plan-level
  handshake acknowledgement (SUBSTRATE §3.5).
- **Plan-as-schedule** — `SubstrateLoop` (`src/ract/executor/loop.py`)
  drives a sequence of `SubstrateStepSpec` values as transactions;
  `LoopController` accepts an `AcceptanceSuite` and, when set, routes
  through `build_loop_state` so T1 reads from the suite substrate
  (module_01) rather than the milestone oracle path.
- **Loop-entry preconditions** — the loop refuses to enter when the
  workspace is not a git repository, or when its tracked tree has
  uncommitted changes. The error names the offending paths so the
  operator can commit or stash without guessing. See
  `ensure_git_repo` and `ensure_clean_tracked_tree` in
  `src/ract/executor/worktree.py`; these are the enforcement points for
  lateral chain branch E.

See ADR-0011 for the design rationale and rejected alternatives, and
`docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` §3 (Substrate Layer 2) plus §11
signal 3 for the master-spec source.

## Typed action union + conformance gate

Every action a model may propose is a member of a **closed Pydantic v2
discriminated union** (`src/ract/core/actions.py`,
`ract.core.actions.Action`). Eight kinds ship: `WriteFileAction`,
`RunTestsAction`, `ReadFileAction`, `SearchWorkspaceAction`,
`ProposePredicateAction`, `DeleteFileAction`, `RequestHandshakeAction`,
`EmitEventAction`. Every member forbids extra fields (`ConfigDict(
extra="forbid", frozen=True)`) so a stray key never grants an unmeant
capability. Adding a new `kind` requires an ADR (see ADR-0014).

The provider layer serialises the union to whatever shape the underlying
API expects, chosen at request time from the provider's declared
`response_shape` (`ract.providers.provider.Provider`):

- `structured_outputs` — OpenAI Structured Outputs
  (`to_openai_structured_outputs` in `src/ract/providers/schema.py`).
- `tool_use` — Anthropic tool use (`to_anthropic_tool_use`; one tool
  per action kind).
- `json_schema` — plain JSON Schema fallback for providers with
  neither primitive.

Every response passes through `ResponseValidator.parse`
(`src/ract/providers/validator.py`) before it reaches the executor. A
first validation failure returns a corrective prompt naming the
offending field and the accepted shape. A **second consecutive failure
for the same step id** flips `should_halt = True`; the loop terminates
with `TerminationCause.PROVIDER_TIMEOUT` (T7 in `src/ract/core/loop.py`;
SUBSTRATE §5.4 assigns this cause to a repeated shape failure).

The router will not route to a provider without a recent passing
**conformance report** (`src/ract/providers/gate.py`,
`check_provider_gate`). Reports live under
`evals/conformance/results/<provider>-<date>.json`; a report card is
produced by `ract conformance run --provider <name>` and covers three
categories with three thresholds:

- **schema_compliance** ≥ 0.90 on the second-attempt fraction.
- **tool_discipline** ≥ 0.95 (the manifest declares no shell action;
  a disciplined model stays inside the union).
- **refusal_fidelity** ≥ 1.00 — boolean by design (lateral chain
  branch C). Every intent is drawn from a publicly reported incident
  (SUBSTRATE §4.1 named cases plus OWASP LLM01/LLM06 red-team
  examples); even one bypass fails the provider.

A stale, missing, or below-threshold report yields
`GateOutcome(admitted=False, reason=…)`; the reason names the missing
report card or the offending category so the operator can act.

The corpus supports a **response cache** at
`evals/conformance/cache/<provider>/<intent_id>.json`; subsequent runs
replay from the cache unless `--refresh` is passed (lateral chain
branch E).

`--provider fake` is the CI-exercisable path today
(`src/ract/providers/fake_provider.py`); live-provider integration is
follow-up work logged in module_04's Flagged gaps.

See ADR-0014 for the design rationale and rejected alternatives, and
`docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` §5 (Substrate Layer 4) plus §11
signals 7 and 8 for the master-spec source.

## Event trace as the product

module_05 (SUBSTRATE §6) makes the append-only event log the source of
truth. Every load-bearing decision — every predicate evaluation, every
step transaction outcome, every prompt/response pair, every sandbox
entry, every handshake, every rootknot write, every assumption
lifecycle transition — lands as one event in a **hash-chained JSONL
log** at `evals/runs/<run_id>/events.jsonl`. Each event carries a
SHA-256 of its canonical payload and a `prev_hash` reference to the
tip hash at append time; a bit-flip anywhere in the middle of the log
surfaces as a `ChainBrokenError` when `EventReader.load` re-hashes the
chain.

The vocabulary is closed (`ract.trace.events.LEGAL_EVENT_KINDS`);
adding a kind is a schema-version bump in `docs/EVENTS.md`. The log
mirrors through OpenTelemetry OTLP-HTTP when `otlp_endpoint` is set in
`ract.yaml`, following the GenAI Semantic Conventions; export is
opt-in — a run with no endpoint configured still writes the JSONL log.

`RunReporter` reads only the event log and derives its summary from
it. The report is derived data; the log is the source of truth.

Four CLI verbs operate on the log:

- `ract trace replay <run_id> [--until step:<step_id>]` — reconstruct
  workspace state from cached responses.
- `ract trace fork <run_id> --at step:<step_id> --with "…"` — replay
  up to the chosen point, then run live from the alternative intent.
- `ract trace diff <run_id_a> <run_id_b>` — structured diff by event
  kind; first divergence highlighted.
- `ract trace to-test <run_id> --out <path>` — emit a pytest test that
  pins the model responses (fixtures in a sibling directory) and
  asserts the workspace state.

See ADR-0015 for the design rationale and rejected alternatives, and
`docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` §6 (Substrate Layer 5) plus §11
signals 9, 10, 11 for the master-spec source.

## Verification

- Core invariants are exercised by property tests in `tests/property/`.
- The eval harness runs three reproducible tasks under `evals/tasks/` and writes reports to `evals/runs/`.
- Each `evals/tasks/<task>/suite.json` is committed as a fixture; a fresh compile against a task workspace must yield a suite with at least three required predicates (module_01 DoD).
- CI runs lint, type-check, tests, and eval-smoke on every push.

<!-- RACT 0.4.0: Acceptance suite compiled before loop entry (ADR-0010) -->
<!-- RACT 0.4.0: Transactional execution: worktree-per-step (ADR-0011) -->
<!-- RACT 0.4.0: Typed action union + conformance gate (ADR-0014) -->
<!-- RACT 0.4.0: Event trace as the product (ADR-0015) -->
