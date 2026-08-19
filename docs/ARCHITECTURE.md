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

## Trust direction: environment attests

module_06 (SUBSTRATE §7 and §8) inverts the trust direction. In v0.3 the
`Rootknot`'s single signature was the *generator*'s — a self-signed
capability whose trust flowed from the author. In v0.4 the
**environment** is the primary attester: every v2 sidecar carries an
`environment_signature` produced by a per-run `SandboxKey`
(`src/ract/security/keys.py`) alongside the `generator_signature`. RK-3
(Environmental Attestation) requires the environment signature to
verify, the `acceptance_suite_digest` and `manifest_digest` to be
currently registered, and `predicate_results` to be non-empty. v1
sidecars from v0.3 workspaces continue to verify under RK-1 + RK-2
only, with a `DeprecationWarning` and refusal under `--strict`. See
`docs/PROVENANCE.md` for the v1 / v2 sidecar compatibility table.

Whisperer, Fence, and Auction move from CLI features to
environment-enforced contracts under `src/ract/contracts/`:

- **`WhispererContract`** runs before every planner call and prepends a
  `DialectBrief` to the prompt. The model does not opt in; the
  environment injects.
- **`FenceGate`** intercepts every `DeleteFileAction` before the
  transaction opens. `open_transaction` refuses a delete action whose
  `fence_ticket_id` is not present in `FenceGate.approved_tickets`
  (`ract.core.transaction.UnfencedDeleteError`).
- **`AuctionSweep`** runs between iterations on the loop's schedule
  (gated by `min_iteration_wall_seconds`) and emits
  `auction.proposal` events. Nothing is deleted without a handshake.

`FenceGate` and `AuctionSweep` compose: an Auction proposal the
operator approves still passes through `FenceGate` at execute time,
because the deletion itself is a `DeleteFileAction`.

`__root_author__` moves to display-only under `ract --about`
(`src/ract/_about.py`); the marker has no role in any invariant and
its absence from other code paths is enforced by
`tests/test_root_author_display_only.py`.

See ADR-0016 and ADR-0017 for the design rationale and rejected
alternatives, and `docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` §7 and §8 plus
§11 signals 12, 13, 15 for the master-spec source.

## Eval-first: borrowed benchmarks locate RACT on the existing map

SUBSTRATE spec §9 (Eval-First as Engineering Discipline) and §11
signal 16. The v0.3 harness ships three RACT-authored tasks under
`evals/tasks/` — enough to prove the harness works, not enough for
the reviewer to locate RACT against the field. Module_07 borrows two
established coding-eval anchors so RACT's numbers become comparable
without inventing a new benchmark:

- **Aider Polyglot** (10-problem deterministic subset under
  `evals/polyglot/`) — Aider's per-provider public leaderboard,
  scored on multi-language edit + test-feedback loops at the
  function-to-file scale. Two attempts per problem, hidden test
  suite, unified-diff output.
- **SWE-bench Lite** (5-instance deterministic pin under
  `evals/swe_bench_lite/`) — the widely-adopted subset of SWE-bench
  where every instance ships as one Docker image, scored on a
  repo-scale issue-to-patch loop with `FAIL_TO_PASS` +
  `PASS_TO_PASS` verification.

Both runners execute each problem/instance inside a fresh
`StepTransaction` (module_02) with a `CapabilityManifest`
(module_03) attached — that is where the substrate proves itself
against real-world workloads.

`evals/LEADERBOARD.md` is the canonical published record. It carries
the four per-corpus columns — Aider Polyglot, SWE-bench Lite,
conformance (module_04), security (module_03) — plus three v0.4.0
ALM columns landed by ALM module_07 (`claimed_pass_rate`,
`attested_pass_rate`, `attestation_gap`). It is regenerated
idempotently by `evals/leaderboard/update.py` from the most recent
report per `(provider, corpus)`. Module-internal `RESULTS.md` files
remain the source of truth for the columns they contribute (Lateral
Chain branch E, substrate module_07); the leaderboard reads them
without duplicating their content. See
`docs/PUBLIC_LEADERBOARD.md` for the column definitions and the
gap-interpretation thresholds; ADR-0025 documents the rejected
alternatives (attested-only, claimed-only, single-combined-score,
model-graded attestation).

The `evals/antilazy/` corpus (10 adversarial cases drawn from
public reward-hacking incidents — SWE-bench Verified `conftest.py`,
Palisade chess-hacking, monkey-patched scorer, patch leakage,
semantic no-op, weak-assertion insertion, under-edit missed callers,
sycophantic reversal, sandbagging, pattern-matching rule-like) is
the source-of-truth for the anti-lazy conformance dimension. Each
case cites its public source in `expected.json` (Lateral Chain
branch A, ALM module_07).

CI runs a smoke tier on every PR against a fixture provider (schema
v2 event streams under `evals/fixtures/providers/`); a nightly
`evals-full.yml` workflow runs the full 10 + 5 sweep against live
providers, gated by the `RACT_EVAL_ENABLED` repository secret so
public forks and PRs do not incur cost (Lateral Chain branch B,
module_07). When an upstream registry or fixture is unreachable, the
runner reports SKIPPED with a specific reason and the CI summary
counts the skip (Lateral Chain branch A).

Every subset revision is an ADR-tracked event (Lateral Chain branch
C); historical numbers remain readable against historical subsets.

Design rationale in `docs/ADRs/ADR-0018-aider-polyglot-swebench-
lite-external-anchors.md`.

## Anti-Lazy Gate G1 (held-out predicates) and Gate G2 (mutation-kill)

ALM spec §3.1 and §3.2; §13 signals 1 and 2. The substrate
``AcceptanceSuite`` already prevents "model votes done, environment
does not"; the ALM turns the pressure one level in. A model that
observes which predicates the suite contains can steer its patch to
satisfy those predicates literally while missing the underlying intent.
G1 and G2 sit between the substrate suite and the pre-commit gate to
close that failure mode.

**Gate G1 — held-out predicate enforcement.** ``IntentCompiler.compile``
accepts an optional ``companion: HoldoutComposer``; when present it
returns a ``DualAcceptanceSuite`` wrapping the substrate
``AcceptanceSuite`` as ``visible`` plus a companion-composed
``held_out`` suite whose canonical JSON is AES-256-GCM sealed under a
symmetric key derived from the run's ``SandboxKey`` via HKDF-SHA256
(context string ``"ract/antilazy/holdout-seal/v1"``, salt = the raw
Ed25519 pubkey bytes). The public ``held_out_digest`` is committed to
``evals/runs/<run_id>/suite.json`` alongside the base64-encoded seal;
the plaintext of the held-out predicates never lands on disk in that
file. The sandbox layer's capability manifest denies read of
``.rack/sandbox/holdout/`` so a model-facing tool cannot request the
seal bytes.

A composer that produces a suite whose predicates evaluate identically
on the current workspace and on a deterministic byte-shuffled
perturbation of the touched surface is marked
``holdout_kind="trivial"`` and T1 treats the held-out half as
auto-pass (lateral chain branch E). This closes the escape hatch where
a model influences the composer into emitting theatre.

T1 (``ract.core.loop.check_t1``) duck-types the dual suite through a
``visible``/``held_out`` attribute pair and calls
``check_visible_and_held_out``, which fires ``laziness.violated`` with
``kind="visible_holdout_gap"`` when the visible half is all-ok but the
held-out half is not. Substrate T1 semantics remain unchanged for
callers that hold a bare ``AcceptanceSuite``.

**Gate G2 — mutation-kill threshold.** After the model claims
completion and before the ``StepTransaction`` commits, ``enforce_g2``
runs mutation testing against the touched surface. A
``MutantSource`` produces mutants (default is a built-in AST-level
arithmetic-operator swap; the ``MutmutSource`` adapter wires to the
optional ``mutmut`` dev dependency), the runner caps per-file mutants
at 200 with deterministic sampling under a fixed seed (lateral chain
branch B), and each mutant is scored against the acceptance suite
under a per-mutant timeout defaulting to 10s. A mutant that exceeds
the timeout lands under ``mutants_survived``, never
``mutants_equivalent``, so a hung evaluator cannot inflate the kill
rate. Surviving mutants are batched into groups of 10 for a single
companion-backed equivalence check per batch (lateral chain branch C);
mutants flagged equivalent land in ``mutants_equivalent`` and are
subtracted from the denominator. Below a 0.7 kill threshold, the gate
returns ``should_roll_back=True`` and emits ``laziness.violated`` with
``kind="mutation_kill_below_threshold"``. The full ``MutationReport``
is persisted to ``evals/runs/<run_id>/mutation.json``.

Both gates land as ALM extensions on top of the substrate; nothing in
``ract.core`` imports from ``ract.antilazy``. The trace vocabulary
gains exactly one new value (``laziness.violated``); every other
event site is reused.

See ADR-0019 for the design rationale and rejected alternatives, and
``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §3.1 and §3.2 for the
master-spec source.

## Anti-Lazy Gate G3 (patch differentiation) and Gate G4 (coverage delta)

ALM spec §3.3 and §3.4; §13 signals 3 and 4. Two more failure modes
the substrate suite and G1/G2 do not close:

- **Semantic no-op patches.** UTBoost measured over 5% of SWE-bench
  Verified instances as diffs that pass the visible suite while
  remaining behaviorally indistinguishable from doing nothing.
- **Solution leakage.** SWE-Bench+ measured 32.67% of the base
  corpus as diffs that byte-match a prior commit — the model
  surfaced training-corpus material rather than authoring the fix.

**Gate G3 — patch differentiation.** ``run_patchdiff(patch, workspace,
generator, runner, baseline_kind="null")`` asks a companion-shaped
``DifferentiatorGenerator`` for pytest-format tests targeting the
functions the diff touches. The generator allocates a total budget
(default 30 tests per transaction, capped per function at 10) with
proportional allocation across touched functions (lateral chain
branch A). Each candidate runs three times against the patch to
filter flaky tests, then keeps only those whose verdict differs
between ``patch`` and the baseline. A diff that touched functions but
produced zero surviving differentiators is ``is_semantic_noop=True``
and rolls back with ``kind="semantic_noop"``.

The leakage fingerprint is a rolling hash (SHA-256) over the newline-
joined added lines per hunk. For every hunk that clears the 5-line /
100-char floor (lateral chain branch B), the scan queries git history
via ``git log --all -S`` and (when supplied) the optional
``RetrievalIndex``. A match surfaces as a ref in ``leakage_matches``;
the report also carries ``leakage_below_floor`` (below-floor hunk
count) and ``retrieval_index_absent`` (lateral chain branch E) so the
reviewer sees what evidence the scan consulted. Non-empty
``leakage_matches`` rolls back with ``kind="solution_leakage"``.

**Gate G4 — coverage delta.** ``run_coverage_delta(parent, child,
patch, mutation_report_parent, mutation_report_child)`` computes
``lines_new = added_lines - moved_lines`` (lateral chain branch C: a
pure refactor moves lines, and moved lines are already covered on the
parent side), reads ``coverage.<path>`` metadata from the child
snapshot to count covered new lines, and returns ``coverage_ratio =
lines_new_covered / lines_new``. Below ``tau_cov = 0.8`` rolls back
with ``kind="coverage_delta_insufficient"``. For non-trivial changes
the mutation-coverage delta between child and parent reports must
exceed ``delta_mut = 0.1``.

A change is trivial iff the substantive added-line count is at or
below 2 and every substantive added line has a whitespace-normalized
match in the removed lines (a pure reformat), or the substantive
added-line count is zero. Trivial changes skip the mutation-delta
check. Non-Python touched files land under ``non_python_files``; the
gate does not measure coverage for them yet (v0.5 backlog).

Both gates land as pure-over-inputs helpers so tests exercise them
without live worktrees; the ``StepTransaction`` pre-commit path calls
them alongside G2. The trace vocabulary gains no new event kind; both
gates emit under ``laziness.violated`` (with ``kind`` payload
discriminators ``semantic_noop``, ``solution_leakage``, and
``coverage_delta_insufficient``) and under ``predicate.evaluated``
(with ``kind="coverage_delta"`` for successful G4 runs).

See ADR-0020 for the design rationale and rejected alternatives, and
``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §3.3 and §3.4 for the
master-spec source.

## Anti-Lazy Gate G5 (test integrity) and Gate G6 (symbol-graph under-edit)

ALM spec §3.5 and §3.6; §13 signals 5 and 6. Two more failure modes
the substrate suite plus G1-G4 do not close:

- **Test-suite tampering.** A patch that passes the visible suite
  because the model deleted assertions, inserted ``pytest.skip``,
  monkey-patched the grader, or edited the conftest that shapes the
  suite. Any reward channel writable from inside the sandbox is a
  channel the model can trivially maximize without solving the
  intent (METR's chess-hacking family).
- **Under-editing.** A patch that renames a symbol or changes a
  signature without updating every downstream caller. The visible
  suite may still pass because the touched call sites were not
  exercised, but the next step lands on a stale reference.

**Gate G5 — sandbox-enforced test integrity.** ``analyze_diff
(parent_snapshot, child_snapshot, config)`` walks the diff between
parent and child workspace snapshots per Python test file. Any hit
against ``config.denied_ast_patterns`` (net-new ``pytest.skip``,
``pytest.xfail``, ``pytest.mark.skip*``),
``config.denied_assertion_transforms`` (``assertion_removal``,
``assert_true_to_pass``), ``config.denied_file_edits``
(``tests/**/*grader*.py``, ``tests/**/conftest.py``), or
``config.monkey_patch_watchlist`` (``sys.modules['grader']``,
``builtins.__import__``, ``sys.settrace``) is a hard-block
violation. The AST analyzer also surfaces metaprogramming shapes —
``getattr(pytest, 'skip')()``, ``pytest.__dict__['skip']()``,
``exec("pytest.skip()")`` — under the pattern
``test_integrity_metaprogramming_escape`` (Second Pass Q1).
``enforce_g5`` rolls the transaction back and emits
``laziness.violated`` with ``kind="test_hack_denied"``. An operator
handshake covering a denied pattern flips the gate to
``passed=True`` and emits the ``handshake.requested`` /
``handshake.resolved`` pair per SUBSTRATE module_05.

Portability skips (``pytest.skip(reason="only on windows")``,
``@pytest.mark.skipif(sys.platform == ...)``) are exempt by the
lateral-branch-A rule — false-positive rollbacks would train the
operator to disable the gate. Test files in TypeScript, Go, and
Rust surface a ``test_integrity_unsupported_language`` advisory
(lateral branch D); the run continues but the coverage gap lands
in the trace so a reviewer can see what evidence the analyzer
consulted.

The ``CapabilityManifest`` grows a strict-mode
``TestIntegrityConfig`` section populated with the §3.5 defaults;
``ManifestValidator`` refuses a manifest whose
``denied_ast_patterns`` or ``denied_file_edits`` is empty
(``code="test_integrity_section_narrowed"``). Narrowing requires a
signed operator handshake — parallel to the tier-3 compile-time
hard-off pattern from ADR-0012.

**Gate G6 — symbol graph and under-edit closure.** ``build_graph
(workspace, cache_db=path)`` parses every Python file in the
snapshot with the stdlib ``ast`` module and produces a
``SymbolGraph`` (``symbols``, ``call_edges``, ``import_edges``,
``generated_files``). The graph persists to
``${WORKSPACE_META}/symgraph.db`` (SQLite) keyed by workspace
snapshot digest (lateral branch B); a fresh call with an unchanged
workspace loads from the cache instead of re-parsing.

``compute_closure(graph, edited_symbols, edited_files,
passing_tests_touched, declared_unaffected)`` returns the set of
downstream callers of the edited symbols, partitioned into
``covered_by_edit`` (caller lives in an edited file),
``covered_by_test`` (a passing test exercises the caller),
``covered_by_declaration`` (the acceptance suite explicitly marks
the caller unaffected), and ``uncovered`` (nothing covers it).
Generated files (from ``.gitattributes linguist-generated=true``
plus a per-language heuristic default — ``*_pb2.py``,
``*_pb2_grpc.py``, ``**/generated/**``, Second Pass Q4) drop from
the downstream set. Getattr-based references (Second Pass Q2) land
in ``getattr_advisories`` — an advisory-only channel because
stdlib ``ast`` cannot see through reflection any more than
tree-sitter could.

Non-empty ``uncovered`` rolls the transaction back with
``kind="under_edit_uncovered_callers"`` and the uncovered caller
list gets injected into the next planning prompt with the message
"the following call sites depend on symbols you just changed.
Update them or explicitly declare them unaffected with rationale."

Both gates land as pure-over-inputs helpers so tests exercise them
without live worktrees. ``WorktreeManager._check_test_integrity``
and ``WorktreeManager._check_under_edit`` are thin delegators; the
substrate merge site calls them in front of ``commit``. The trace
vocabulary gains no new event kind — both emit under
``laziness.violated`` (with ``kind`` payload discriminators
``test_hack_denied`` and ``under_edit_uncovered_callers``) and
under ``predicate.evaluated`` (with
``kind="test_integrity_advisory"`` for passing runs that had
advisories).

Design decision (v0.4.0-rc1): stdlib ``ast`` ships as the parser
rather than tree-sitter. Python-only coverage is what the DoD
requires; tree-sitter is a v0.5 backlog switch when the language
expansion pipeline actually needs the wider grammar. Extension
points for TypeScript, Go, and Rust are declared and
stub-implemented today; the switch is a parser change, not an
API change.

See ADR-0021 for the design rationale and rejected alternatives,
and ``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §3.5 and §3.6 for the
master-spec source.

## Anti-Lazy Gate G7 (companion red team) and Gate G8 (effort reconciliation)

ALM module_04 adds the last two completion-path gates before the
sycophancy circuit lands in module_05.

**G7 (companion red team).** A cold-context second provider receives
only the intent, the final diff, and the visible predicates (never
the held-out ones, never the event trace, never the primary's turn
history). Its job is to propose counterexamples that break the
completion claim. The companion runs in a read-only workspace mount
(``bwrap`` on Linux, ``seatbelt`` on macOS) with a 2-minute wall-time
budget. A surviving counterexample — one that passes on the
pre-change workspace and fails on the post-change workspace — emits
``laziness.violated`` with ``kind="companion_counterexample"`` and
the loop resumes with the counterexamples injected into the next
planning prompt.

The router-level different-provider constraint refuses to schedule a
companion whose ``Provider.name`` matches the current primary or any
of the last three primary-step providers; matches raise
``CompanionProviderCollisionError``. Single-provider deployments opt
into ``deployment_mode="single_provider_advisory"`` and get
advisory-only findings (they log but do not block).

**G8 (effort reconciliation).** Before the loop enters step one, a
static-heuristic estimator produces a low-precision effort estimate
from the workspace: grep density of intent keywords against filenames,
symbol-graph fanout of matched entry points, existing test-to-symbol
ratio, per-symbol median lines from git history. No model call, so
the primary cannot frame the intent to bias the estimate. Keyword
extraction drops tokens that hit more than half of workspace
filenames as low-signal (Second Pass Q3 defense against
keyword-packing). After T1 fires, realized effort is measured from
the final diff; a ratio below ``tau_effort`` (default 0.3) on any
dimension queues a suspicion prompt and holds COMPLETE until the
primary either enumerates skipped items with justification or
produces additional work that closes the anomaly.

The completion-gate wiring lives in
``ract.antilazy.completion_gate.run_completion_gates``; the
``LoopController`` calls it after T1 predicate evaluation and reads
``blocks_complete`` from the returned ``CompletionGateOutcome`` to
decide whether to terminate or queue the resume prompt.

The router-gate ``GateConfig`` extends with
``anti_lazy_conformance: float = 0.7``; providers below the floor
are refused for both primary and companion roles at registration.
``evals/conformance/COMPANION_MATRIX.md`` publishes the eligible
primary-companion pairs (different training family, anti-lazy score
≥ 0.7, schema score ≥ 0.9); it is regenerated idempotently by
``evals/leaderboard/update_companion_matrix.py``.

Module_04 also closes module_01's flagged gap on
``holdout_kind="trivial"``: a per-pipeline trivial-rate ceiling
(``enforce_trivial_rate_ceiling`` in ``ract.antilazy.holdout``)
refuses to compile a new held-out suite when the composer's rolling
trivial rate exceeds 0.3 over the last 20 compositions. The gap
becomes a loud refusal (``TrivialRateCeilingExceededError``) instead
of a silent auto-pass.

See ADR-0022 for the design rationale and rejected alternatives, and
``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §3.7 and §3.8 for the master-
spec source.

## Anti-Lazy Attestation: three signatures and Invariant AL-1

ALM module_05 lands the sacred-spine change: the Rootknot gains a third
signature (``antilazy_signature``), a snapshot of the eight anti-lazy
gate outcomes (``gate_results``), and a taint value the sycophancy
circuit produces (``reversal_taint``). ``schema_version`` bumps to 3;
``canonical_bytes`` dispatches on the version so v1 (v0.3) and v2 (v0.4
substrate) rootknots continue to verify under the compatibility reader.

**The three signatures.** A v3 Rootknot carries the generator signature
(session key, RK-1.2), the environment signature (sandbox key, RK-3.1),
and the anti-lazy signature (ALM verifier key, AL-1.1). The three keys
live in three separate processes: model layer, sandbox, ALM verifier.
Compromising any one does not forge the others.

**Invariant AL-1 (Anti-Lazy Attestation).** ``verify_workspace`` runs
three sub-clauses per v3 rootknot:

- AL-1.1 ``knot.antilazy_signature`` verifies under the ALM verifier
  pubkey the resolver returns.
- AL-1.2 every ``GateResult`` in ``knot.gate_results`` has
  ``passed=True`` OR carries a ``handshake_id`` that appears in
  ``approved_gate_exceptions`` (the operator's approved-handshake ids
  read from the ``HandshakeRegistry``).
- AL-1.3 ``knot.reversal_taint == "clean"`` OR the run identified by
  ``knot.plan_id`` appears in ``accepted_partial_taint_runs`` (the
  operator's point-in-time acceptance of the partial taint).

Under ``strict=True`` the bar rises to "AL-1 required" the same way
module_06 raised it to "RK-3 required": pre-v3 sidecars are refused
outright.

**Sycophancy circuit breaker (``ract.antilazy.sycophancy``).** The
scanner reads the event trace for assistant turns that flip position
within a five-turn window without intervening evidence (predicate
evaluation, tool result, companion response, or Investigator report).
Position classification is deterministic (regex plus small heuristic
ledger) so the sycophancy detector is independent of the primary
provider. A suspicious reversal fires a forcing prompt via
``force_evidence_or_restore``; unresolved suspicious reversals set
``reversal_taint`` to ``partial``. The two-consecutive-reversal gate
plus the Investigator-report exemption keep the false-positive rate
bounded.

**Investigator (``ract.antilazy.investigator``).** A pre-completion
contract that reads files the primary loop did not touch. Files are
selected by symbol-graph adjacency (import + call edges) to touched
symbols; the top 20 by score are opened (Lateral Chain branch B). The
selection pads with lexicographically-earliest untouched files when
the adjacency ranking is shorter than the bound, so a primary that
tries to name no symbols the graph would connect to hidden files still
cannot cap the Investigator's reach (Second Pass Q3 defence). The
Investigator's probe is a companion-provider callable (different
family per G7); its report is required input to G6 and G7. A
completion without an ``investigator.report`` event in the trace emits
``laziness.violated`` with ``kind="investigator_missing"`` and does
not authenticate.

**ALM verifier key chain of custody.** The v3 sidecar embeds the ALM
pubkey the sidecar was signed under. This is trust-by-declaration:
the sidecar carries both the signature and the pubkey that verifies
it. The verifier is REQUIRED to cross-check the embedded pubkey
against an out-of-sidecar source: a resolver passed as ``alm_pubkey``
to ``verify_workspace`` (typically a lookup into the workspace-level
``.rack/alm/archive/*.key`` file the ALM verifier process wrote at
run close, or an operator-supplied registry). The
``load_sidecar_alm_pubkey`` docstring documents this explicitly. See
ADR-0023.

See ``docs/RACT_v0.4.0_ANTILAZY_SPEC.md`` §4, §5, §8, §10 for the
master-spec source.

## Anti-Lazy Isomorphic Perturbation Gate

ALM master spec §9. An optional completion-path gate that fires only
when the intent is rule-like — universally quantified ("every user
must have exactly one primary email"; "no function may bypass the
audit logger"; "all monetary values are stored as integer cents").
The gate restates the intent under three isomorphic transformations
(rename entities, swap syntax, permute example order) and dispatches
each transformed variant to the primary provider with the same
workspace. Solutions are compared under AST-normalized digest with
the rename map applied in reverse; divergence emits
``laziness.violated`` with ``kind="isomorphic_divergence"`` and blocks
COMPLETE, injecting the divergence as evidence into the next
planning turn.

**Detector (``ract.antilazy.iso_perturb.detect_rule_like_intent``).**
Stdlib-regex over the universal-quantifier keywords (``every``,
``all``, ``no``, ``exactly one``) and the modal keywords (``must``,
``never``, ``always``, ``cannot``). Returns a ``RuleLikeDetection``
with a ``confidence`` score; below 0.7 confidence the caller runs one
transformation instead of three (lateral chain branch A). The
detector is deliberately over-inclusive — a false positive costs one
extra companion dispatch, a false negative loses the gate entirely,
which is the more expensive error.

**Compile pass (``IntentCompiler.compile_and_detect_rule_like``).**
The rule-like flag rides alongside the ``AcceptanceSuite`` return so
loop wiring reads a single ``(suite, rule_like)`` tuple and does not
re-parse the intent. Substrate callers that call ``compile`` see the
old return shape unchanged.

**Transformations (``transform_intent``).** Deterministic, stdlib
only. ``rename_entities`` substitutes free variables against a fixed
synonym table; identifiers in ``workspace_symbols`` pass through
unchanged so the rename does not shift domain vocabulary (lateral
chain branch B). ``swap_syntax`` reorders clauses via a small
sentence-splitter pass. ``permute_examples`` reverses dash-prefixed,
numeric-prefixed, or comma-quoted lists inside the intent. The three
variants are always returned in the same fixed order so the
transformed-solution digests stay stable across runs.

**AST-normalized comparison (``compare_solutions``).** When both the
original and transformed solutions parse as Python, the reverse
renaming map is applied to the transformed solution and both are
compared via ``ast.dump``. Exact match returns similarity 1.0 with
no divergence reason. Below the similarity threshold the divergence
reason is one of ``ast_dump_mismatch``, ``parse_failure_original``,
``parse_failure_transformed``, ``string_similarity_below_threshold``,
or ``solution_missing`` (closed vocabulary). Non-Python solutions
fall back to ``difflib.SequenceMatcher.ratio`` and emit an advisory
under lateral chain branch C.

**Loop wiring (``LoopController.iso_perturb``).** An optional
``IsoPerturbBundle`` (primary ``SolutionProducer``, optional
companion, config, workspace-symbol preservation set, report
directory). When present, the loop's completion callback runs the
gate after the module_04 completion gates. Divergence writes the
resume prompt into ``_repair_intent`` and returns
``blocks_complete=True`` so the loop does not terminate COMPLETE.
The gate itself internally checks rule-like detection and returns
``skipped_reason="non_rule_like"`` for non-rule-like intents,
matching the DoD "the gate does not fire on non-rule-like intents".

**Orthogonality with G1 (lateral chain branch D).** G1 verifies that
the specific solution passes the held-out predicates the composer
wrote. Iso-perturbation verifies that the solution's SHAPE is
invariant under transformation of the intent. Different questions;
both run when the intent is rule-like. See ADR-0024 for the
explicit note in the "Rejected alternatives" and "Interaction with
G1" sections.

**Report at ``evals/runs/<run_id>/iso_perturb.json``.** The canonical
form carries the original intent, the transformations with their
renaming maps, the original and transformed solution digests, the
divergences, and the ``is_pattern_matching`` flag. Written on every
rule-like completion for retrospective audit. See ADR-0024.

## Token budget system (v0.5.0 memory discipline)

Every function that reaches a model in v0.5.0 declares a budget
structure and every write into the assembled context passes through a
per-invocation :class:`BudgetAccountant`. The accountant is the
pre-model gate: on over-ceiling it refuses the invocation BEFORE the
model call and emits ``budget.exceeded`` to the event trace.

Surface: ``src/ract/memory/budget.py`` (accountant + declaration +
narrowing types), ``src/ract/memory/budget_defaults.yaml`` (per-
function defaults), ``src/ract/memory/budget_registry.py`` (typed
loader), ``src/ract/memory/composition.py`` (playbook override +
runtime narrowing), ``src/ract/memory/events.py`` (null-sink emitter
helpers for the seven memory-discipline event kinds; module_09
swaps the null sink for :class:`JsonlEventWriter` and bumps the
closed EventKind vocabulary).

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The
token budget system. Rationale: ADR-0031.

Three sources feed the budget in precedence order: the function
default from ``budget_defaults.yaml``; the composition override from
the playbook YAML for the current use case (module_07); the runtime
adjustment from the self-adjustment layer (module_08). Runtime
adjustment ALWAYS narrows, never widens; widening is a design change
that requires a fresh function-default commit. Both narrowing paths
refuse widening at construct time and at helper time (belt-and-
suspenders).

Sacred spine anchor: ``tests/memory/test_budget_ceiling.py::
test_over_ceiling_refuses_invocation_before_model_call``.

## Symbol index (v0.5.0 memory discipline)

The first of the three memory-discipline indexes. SQLite-backed
store at ``.rack/index/symbols.db`` with an FTS5 mirror for
docstring + name full-text search. Tree-sitter parses Python,
TypeScript, Rust, and Go into a flat symbol list per file; the
store is language-agnostic so ``find_by_name("User")`` returns
Python + TypeScript matches in one result set.

Surface: ``src/ract/memory/symbol_index.py`` (store + query API +
:class:`SymbolRow`), ``src/ract/memory/symbol_index_schema.sql``
(canonical schema), ``src/ract/memory/parser.py`` (extension
dispatch + content-hash + token-count helpers),
``src/ract/memory/languages/{python,typescript,rust,go}.py`` (per-
language tree-sitter chunking with pinned grammar versions),
``src/ract/memory/walker.py`` (``.gitignore`` + ``.ractignore``
respecting file walk + ``initial_build``), and
``src/ract/memory/watcher.py`` (``watchdog`` observer +
per-path debouncer + periodic mtime-scan fallback).

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The
three indexes / Symbol index. Rationale: ADR-0032.

Grammar pins are load-bearing: each language module refuses to load
on a mismatched ``tree-sitter-<lang>`` distribution version, so a
silent AST-node-kind rename cannot degrade the parse. The watcher
runs two invalidation paths side by side; the periodic mtime scan
lives on its own daemon thread so a slow parse cannot block
missed-save recovery on Windows.

Sacred spine anchor for FTS mirror consistency:
``tests/memory/test_symbol_index.py::
test_find_by_text_reflects_update_in_same_transaction``.

## Graph index (v0.5.0 memory discipline)

The second of the three memory-discipline indexes. SQLite-backed
store at ``.rack/index/graph.db`` with an ``edges`` table keyed on
``(source_symbol_id, target_symbol_id, edge_type, location_file,
location_line)``. Every edge references ``symbols.id`` from the
module_02 store; the two stores are separate SQLite databases and
maintain referential integrity through the graph populator's
source-file-scoped delete + re-insert path rather than declared
foreign keys.

Surface: ``src/ract/memory/graph_index.py`` (store + query API +
:class:`EdgeRow`), ``src/ract/memory/graph_index_schema.sql``
(canonical schema), ``src/ract/memory/lsp.py`` (multilspy wrapper +
per-language adapter map + synthetic probe),
``src/ract/memory/graph_populator.py`` (LSP-driven initial build +
per-file update + probe-cache), and
``src/ract/memory/lsp_fallback.py`` (symbol-only degradation with
``neighborhood_source='symbol_only'`` marker).

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The
three indexes / Graph index. Rationale: ADR-0033.

Query API:
:meth:`GraphIndex.callers_of` /
:meth:`GraphIndex.callees_of` (1..N hops, exclude symbol-only
edges from transitive walks), :meth:`GraphIndex.blast_radius`
(symmetric N-hop reach as :class:`SymbolRow` set),
:meth:`GraphIndex.path_between` (shortest edge path, BFS with
``max_hops`` guard), :meth:`GraphIndex.orphans` (dead-code
candidates; ``exclude_public=True`` by default so the public API
is not surfaced), :meth:`GraphIndex.hotspots` (edges at or above
a strength threshold).

Every query helper accepts an optional
:class:`~ract.memory.budget.BudgetAccountant` so a caller
building a retrieval bundle for a model call seats the traversal
cost against the same accountant that gates the invocation
(memory-discipline axiom 1).

LSP fallback: when :func:`~ract.memory.lsp.probe_lsp` reports a
language as unavailable, the populator invokes
:func:`~ract.memory.lsp_fallback.populate_symbol_only` and
inserts one self-referential edge per symbol under that language;
edges are marked ``neighborhood_source='symbol_only'`` so
downstream retrieval (module_05) treats them as "no
neighborhood" rather than a callback loop.

Recommended LSP installs (per-platform):

- Python: ``pip install jedi-language-server`` (bundled with
  multilspy default) or ``pip install python-lsp-server``.
- TypeScript: ``npm install -g typescript-language-server
  typescript``.
- Rust: ``rustup component add rust-analyzer``.
- Go: ``go install golang.org/x/tools/gopls@latest``.

## Semantic index (v0.5.0 memory discipline)

The third of the three memory-discipline indexes. LanceDB-backed
vector store at ``.rack/index/semantic/`` with one embedding per
AST chunk. Chunks derive from the module_02
:class:`~ract.memory.symbol_index.SymbolRow` records; small symbols
produce one chunk, symbols over the 500-token cap split at logical
boundaries (blank-line groups + line-count fallback) with the parent
signature prepended to every sub-chunk.

Surface: ``src/ract/memory/semantic_index.py``
(:class:`SemanticIndex` store + :class:`ChunkRow` value type + query
API), ``src/ract/memory/embedding.py``
(:class:`~ract.memory.embedding.EmbeddingModel` protocol +
:class:`~ract.memory.embedding.BgeSmallEmbedding` /
:class:`~ract.memory.embedding.NomicEmbedTextEmbedding` real
wrappers + :class:`~ract.memory.embedding.SyntheticHashEmbedding`
offline / CI fallback + :func:`~ract.memory.embedding.load_embedding`
dispatch), ``src/ract/memory/chunker.py``
(:func:`~ract.memory.chunker.chunk_symbol` splitter + oversize
warning), ``src/ract/memory/semantic_builder.py`` (initial + per-
symbol build path + parent-symbol linkage helper), and
``src/ract/memory/cpu_fallback.py``
(:func:`~ract.memory.cpu_fallback.probe_lancedb` + backend override).

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The
three indexes / Semantic index + §Chunk discipline. Rationale:
ADR-0034.

Query API: :meth:`SemanticIndex.search` (top-k vector search with
optional filter), :meth:`SemanticIndex.search_by_symbol` (mean-
vector query over the seed symbol's chunks, excluding the seed
itself), :meth:`SemanticIndex.search_with_budget` (returns as many
top-k results as fit under a caller-supplied token cap; skips
individual chunks that overflow the remaining budget so a later
smaller chunk can still fit — Second Pass Q1 pack-greedy-by-
relevance),
:meth:`SemanticIndex.enrich_with_graph` (one-hop graph enrichment
on semantic hits with default
``neighborhood_source='lsp'`` filter — module_03 POST inbound
constraint 1).

Every write path (:meth:`insert_or_update` / batch variant /
:meth:`delete_by_symbol` / :meth:`delete_by_file`) validates the
vector dim against the store's embedder and rejects chunks whose
``chunk_kind`` is outside the shipped :data:`CHUNK_KINDS`
vocabulary. Store identity is protected by
``metadata.json`` alongside the LanceDB directory: a re-open
under a different embedder raises
:class:`~ract.memory.semantic_index.EmbeddingModelMismatchError`;
metadata missing while the ``chunks`` table exists raises
:class:`~ract.memory.semantic_index.SemanticStoreCorruptError`
(Second Pass Q4).

Chunk identity joins on module_02
:attr:`~ract.memory.symbol_index.SymbolRow.content_hash` and the
``symbols.id`` foreign key; no parallel symbol id space is created
(module_02 POST inbound constraint 2). The semantic-builder's
initial pass also populates
:attr:`~ract.memory.symbol_index.SymbolRow.parent_symbol_id` for
method-kind rows against their class-container line ranges
(module_03 POST inbound constraint 2 — the schema column has been
unused since module_02 and lands its first writer here).

Offline install path: ``sentence-transformers`` is an OPTIONAL
extra (``pip install ract[embedding]``). Callers who want a real
BGE / Nomic model set either ``RACT_EMBED_ONLINE=1`` to allow the
HuggingFace download or point
``RACT_EMBED_MODEL_ROOT=<dir>`` at a directory containing
``<dir>/bge-small-en-v1.5/`` weights. Offline / CI paths use
:class:`~ract.memory.embedding.SyntheticHashEmbedding` which
produces deterministic (identity-preserving, not semantic) vectors
per text so the store + query API surface fully under test.

LanceDB availability is probed at open time by
:func:`~ract.memory.cpu_fallback.probe_lancedb`; the result is on
the store instance as ``lance_probe`` for diagnostic use. The
``RACT_LANCEDB_BACKEND`` env var forces GPU or CPU regardless of
the auto-probe.

## Retrieve primitive (v0.5.0 memory discipline)

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §The
retrieve primitive + §Retrieval cascade + §Cache layer. Rationale:
ADR-0035.

The retrieve primitive is the composition point over the three
memory-discipline indexes. It takes a
:class:`~ract.memory.retrieve.RetrievalQuery` (symbol names,
keywords, graph seeds, direction, hops, file scope, exclude paths),
a list of :class:`~ract.memory.retrieve.IndexRef` (one per available
index), a token :data:`~ract.memory.retrieve.TokenBudget`, a
:class:`~ract.memory.chunk.ChunkFormat`, and a
:class:`~ract.memory.retrieve.RetrievalStrategy`; returns a
:class:`~ract.memory.retrieve.RetrievalBundle` with the chunks that
fit under budget plus a full query trace.

Surface: ``src/ract/memory/retrieve.py`` (the ``retrieve`` function
+ dataclasses + ``BoundedContextError`` + ``NestedRetrievalError``),
``src/ract/memory/chunk.py`` (:class:`~ract.memory.chunk.Chunk` +
:func:`~ract.memory.chunk.format_chunk` +
:func:`~ract.memory.chunk.chunk_from_symbol` +
:func:`~ract.memory.chunk.chunk_from_chunk_row`),
``src/ract/memory/cache.py``
(:class:`~ract.memory.cache.RetrievalCache` SQLite store with
per-symbol + per-file invalidation), and
``src/ract/memory/query_trace.py``
(:class:`~ract.memory.query_trace.QueryTrace` +
:class:`~ract.memory.query_trace.IndexHit` +
:class:`~ract.memory.query_trace.CascadeStep` +
:func:`~ract.memory.query_trace.to_canonical_json`).

Cascade shape (four levels; per master spec §Retrieval cascade):

1. Level 1. FULL for every match. If under budget, return.
2. Level 2. FULL for exact and graph; SIGNATURE for keyword and
   semantic.
3. Level 3. FULL for exact; SIGNATURE for graph; drop semantic.
4. Level 4. SIGNATURE for exact; drop everything else. Return with
   ``dropped_symbols`` populated.
5. Refuse. If Level 4 still exceeds budget, raise
   :class:`~ract.memory.retrieve.BoundedContextError` and emit
   ``retrieval.refused``.

Termination is bounded by construction: the primitive gathers every
candidate once at entry, then re-renders one fixed pool per level.
Growth is impossible because the per-level format table only drops
or shrinks (never adds). ``test_cascade_never_loops_returns_or_refuses``
is the sacred-spine anchor.

Cache: SQLite at ``.rack/cache/retrieval.db`` (WAL enabled). Key
digest is SHA-256 over ``canonical_json(query) + repo_commit_hash``.
Each entry records the referenced symbol id list plus file path list
so :meth:`~ract.memory.cache.RetrievalCache.invalidate_by_symbol`
and :meth:`~ract.memory.cache.RetrievalCache.invalidate_by_file`
drop matching entries on a watcher save. Different commit hashes
produce distinct cache keys, so a cache hit against the old commit
can persist under its old key without polluting the new commit's
answers.

Chunk formats: FULL / BODY_ONLY / SIGNATURE / SUMMARY. SUMMARY
delegates to a provider ``summarize(chunk)`` call; without a
provider the returned chunk carries
``body = "summary unavailable"`` and
:attr:`~ract.memory.chunk.Chunk.summary_pending` is ``True``. A
real provider integration lands in module_06 alongside the four
function contracts.

Inbound-constraint honors:

- Bundle dedup runs on
  :attr:`~ract.memory.chunk.Chunk.content_hash`, not ``chunk_id``
  (module_04 POST inbound constraint 3).
- Oversize chunks are surfaced with a note in
  :attr:`~ract.memory.retrieve.RetrievalBundle.truncation_notes`
  rather than silently stripped (module_04 POST constraint 2).
- The greedy relevance-order per-level pack is intentional; a
  knapsack-optimal per-level DP (module_04 POST constraint 1) is
  Flagged gap 1 owned by module_06.
- Mid-invocation retrieve depth > 1 refuses with
  :class:`~ract.memory.retrieve.NestedRetrievalError` (Lateral Chain
  branch B; adversarial reviewer Q4).
- Cache invalidation is per-symbol; the graph-edge staleness case
  (reviewer Q2 pre-declared) is Flagged gap 3.

Events emitted (all null-sink until module_09 wires the real sink):
``retrieval.requested`` at entry, ``retrieval.cascaded`` on every
downgrade, ``retrieval.satisfied`` on successful return,
``retrieval.refused`` on cascade exhaustion.

## Function contracts (v0.5.0 memory discipline)

Four verbs at `src/ract/memory/functions/` carry a change from user
request through to a candidate diff. Master spec §Function
contracts; ADR-0036.

- `intake(request, context, provider)` → `WorkOrder`. Budget 4k.
  Reads git log, README head, mentioned-symbol signatures. No code
  bodies.
- `research(work_order, indexes, provider)` → `ResearchBundle`.
  Budget 10k. Consumes `retrieve()` at SIGNATURE format with
  `CORE_FIRST` strategy. Raises `EmptyResearchError` on zero
  relevant symbols; `OversizedResearchError` if the pool exceeds
  50 symbols after one recursive narrowing pass.
- `plan(work_order, research_bundle, indexes, provider)` →
  `ChangePlan`. Budget 9k. May issue up to three mid-invocation
  `retrieve()` calls at 500-token sub-budgets each (`depth=1`,
  bounded by module_05's `NestedRetrievalError`). Raises
  `InfeasiblePlanError` on empty target_symbols.
- `edit(change_plan, indexes, provider)` → `CandidateDiff`. Budget
  18k. Cascade tier 1 loads FULL for every load_manifest entry;
  tier 2 downgrades non-targets to SIGNATURE; tier 3 to BODY_ONLY;
  tier 4 attempts target-only. Raises `BoundedContextError` if
  targets alone exceed input_target. Diff output passes a lazy-token
  + ellipsis-body + prose-placeholder validator; up to two retries
  with the validator reasons appended. Raises `InvalidSyntaxError`
  on third failure.

The four output contracts (`WorkOrder`, `ResearchBundle`,
`ChangePlan`, `CandidateDiff`) live at
`src/ract/memory/functions/contracts.py` as frozen dataclasses with
canonical JSON round-trip via `to_json` / `from_json`.

Shared plumbing:

- `errors.py` — `MemoryFunctionError` base class + six subclasses
  the composition layer catches once and dispatches per subclass
  (Lateral Chain branch D).
- `provider_adapter.py` — `MemoryFunctionProvider.send(prompt,
  declaration) -> str` protocol; `assemble_prompt` five-section
  composer per master spec §Context composition;
  `refuse_over_ceiling` pre-model refuse gate.
- `prompts_loader.py` — loads `prompts/{function}_v{n}.md`;
  `assert_prompt_shipped` fires at import time so a version-string
  bump without a matching prompt file surfaces before the first
  invocation (Second Pass Q4 defence).
- `testing/mock_provider.py` — canned-response `MockProvider` for
  tests (Lateral Chain branch B).
- `session.py` — `SessionMemory` per-run store; persists to
  `evals/runs/<run_id>/session.json` after every write.

Structured generation for edit output is a lightweight post-generation
validator in v0.5.0 (see ADR-0036 §Alternative 3); grammar-constrained
generation via Outlines defers to v0.6.

The four v0.6 verbs (`verify`, `review`, `commit`, `document`)
defer per master spec §Bounded scope.

## Verification

- Core invariants are exercised by property tests in `tests/property/`.
- The eval harness runs three reproducible v0.3 tasks under `evals/tasks/` and writes reports to `evals/runs/`.
- Each `evals/tasks/<task>/suite.json` is committed as a fixture; a fresh compile against a task workspace must yield a suite with at least three required predicates (module_01 DoD).
- The v0.4 Aider Polyglot and SWE-bench Lite runners under `evals/polyglot/` and `evals/swe_bench_lite/` produce per-provider reports under `evals/runs/<date>-<corpus>-<provider>.{json,md}`; `evals/LEADERBOARD.md` is regenerated idempotently by `evals/leaderboard/update.py`.
- CI runs lint, type-check, tests, eval-smoke (v0.3 tasks + v0.4 polyglot smoke + v0.4 swebench_lite smoke against a fixture provider), and the LEADERBOARD regenerator on every push.

<!-- RACT 0.4.0: Acceptance suite compiled before loop entry (ADR-0010) -->
<!-- RACT 0.4.0: Transactional execution: worktree-per-step (ADR-0011) -->
<!-- RACT 0.4.0: Typed action union + conformance gate (ADR-0014) -->
<!-- RACT 0.4.0: Event trace as the product (ADR-0015) -->
<!-- RACT 0.4.0: Rootknot environment attestation + contracts (ADR-0016, ADR-0017) -->
<!-- RACT 0.4.0: Eval-first — Aider Polyglot + SWE-bench Lite anchors (ADR-0018) -->
<!-- RACT 0.4.0-rc1: Anti-Lazy Gate G1 (held-out) + Gate G2 (mutation-kill) (ADR-0019) -->
<!-- RACT 0.4.0-rc1: Anti-Lazy Gate G3 (patch differentiation) + Gate G4 (coverage delta) (ADR-0020) -->
<!-- RACT 0.4.0-rc1: Anti-Lazy Gate G5 (test integrity) + Gate G6 (symbol-graph under-edit) (ADR-0021) -->
<!-- RACT 0.4.0-rc1: Anti-Lazy Gate G7 (companion red team) + Gate G8 (effort reconciliation) (ADR-0022) -->
<!-- RACT 0.4.0-rc1: Three-signature Rootknot + Invariant AL-1 + sycophancy circuit + Investigator (ADR-0023) -->
<!-- RACT 0.4.0-rc1: Isomorphic Perturbation gate for rule-like intents (ADR-0024) -->
<!-- RACT 0.5.0: Token budget system + budget accountant hard-ceiling refuse (ADR-0031) -->
<!-- RACT 0.5.0: Symbol index — SQLite + tree-sitter + FTS5 + incremental file watcher (ADR-0032) -->
<!-- RACT 0.5.0: Graph index — SQLite edges + multilspy LSP driver + symbol-only fallback (ADR-0033) -->
<!-- RACT 0.5.0: Semantic index via LanceDB + local embedding model (ADR-0034) -->
<!-- RACT 0.5.0: Retrieve primitive with four-level cascade (ADR-0035) -->
