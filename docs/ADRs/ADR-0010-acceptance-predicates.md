# ADR-0010: Acceptance Predicates as External Verifiers

## Status

Accepted

## Context

In v0.3, T1 (Completion) in the RACT recursion loop was decided by the
`MilestoneOracle`: a model-graded judgment about model output. The loop
would terminate `COMPLETE` when the oracle reported every milestone
`verified` at confidence `>= tau_complete`. The failure mode is
structural: the same manager LM that generated the artifacts votes on
whether they satisfy the intent. That is a model grading its own
homework, and the audit against `docs/RACT_v0.4.0_SUBSTRATE_SPEC.md`
§11 signal 2 marked it MISSING.

Two collateral failure modes follow from the model-graded oracle:

- A high-confidence oracle verdict short-circuits the environment. If the
  workspace has drifted (missing test file, broken artifact, type error),
  the environment has no independent say. Termination is a text judgment
  by a text model.
- Acceptance is opaque post-mortem. There is no artifact a reviewer can
  read to reconstruct what "done" meant for a run; the exit condition
  lives inside the oracle prompt and the model's response.

The substrate rebuild inverts this. Termination must be a fact about the
environment.

## Decision

An `IntentCompiler` (`src/ract/core/compile.py`) compiles every intent
into a frozen `AcceptanceSuite` (`src/ract/core/predicate.py`) **before**
the loop enters step one. The suite is a tuple of
`AcceptancePredicate` values, each carrying an id (16-byte UUID), a kind
(`test | type | property | invariant | artifact`), a concrete
`PredicateInvocation`, a `required` flag, and a tuple of dependency ids.

- **T1 is a fact about the environment.** `check_t1(suite, snapshot)`
  returns `TerminationCause.COMPLETE` if and only if every required
  predicate evaluates `ok=True` against the workspace snapshot. No model
  opinion terminates the loop.
- **Evaluators are pure over `(invocation, snapshot)`.** Built-in
  evaluators live in `src/ract/core/gates.py`. When the underlying
  verification would otherwise mutate state (e.g., a live pytest run),
  the evaluator reads pre-computed results from
  `WorkspaceSnapshot.metadata`. Live execution against a scratch copy of
  the snapshot is deferred to module_02's worktree substrate; this ADR
  documents the coupling but does not enforce it.
- **The suite is persisted before the first step runs.**
  `build_loop_state(..., run_dir=<run_dir>)` writes
  `evals/runs/<run_id>/suite.json` (canonical JSON, sorted keys) before
  returning. Every run has an on-disk artifact naming its exit condition.
- **The compiler proposes; the operator approves.** New tests, new
  properties, or new artifact requirements the compiler proposes are
  grouped by kind and blocked behind a single grouped handshake per kind
  (one handshake per group with a diff-shaped preview, not one handshake
  per predicate). Only approved groups enter the frozen suite.
- **Zero-required-predicate suites are refused at the loop
  constructor.** `LoopState.__post_init__` raises `ValueError` naming the
  intent id if the suite has no required predicates, so an open-ended
  intent ("refactor for readability") cannot trivially satisfy T1 by
  producing an empty suite.
- **Coverage gate is a required predicate.** SUBSTRATE §2.4 lists
  coverage as a source; adding it to the required set means a drop in
  coverage refuses to fire `COMPLETE` — the coverage floor is enforced
  by the environment, not policed after the fact.
- **The suite is versioned.**
  `AcceptanceSuite.compiler_version` is a canonical string; the reader
  (`suite_from_canonical`) dispatches on the version and refuses unknown
  values, per the same policy as ADR-0008 (`ract.yaml` schema
  versioning). Older suites deserialize under a compatibility path when
  new versions ship; unknown versions halt rather than silently
  reinterpret.
- **`ProgressOracle` survives as a scheduling heuristic.** It still
  returns a score, but T1 no longer consumes it. The score feeds T2
  (regression detection) and reporting only.
- **`RunReporter` projects the suite.** `render_acceptance_suite`
  renders the full suite and every `PredicateResult` from the final
  snapshot, so a reviewer can read the exit condition and what the
  environment observed without running the tool.

## Consequences

- Termination is falsifiable off a text artifact. A reviewer inspects
  `suite.json` and the final-snapshot `PredicateResult` set; the loop's
  exit is a boolean over external facts.
- The pressure on the compiler is up-front. The compiler must produce a
  non-trivial suite for real intents; if it cannot, the load-bearing
  assumption (SUBSTRATE §2 and this module's depth chain) is refuted.
  The three v0.3 eval tasks (`refactor-function`, `fastapi-validation`,
  `file-watcher`) each compile to a fixture suite with `>= 3` required
  predicates and those fixtures are committed under
  `evals/tasks/<task>/suite.json`.
- The model cannot lower its own exit condition mid-loop. Post-hoc test
  generation during the loop is refused — the suite is frozen before
  step one and mutating a frozen dataclass raises.
- `LoopState` gains a required `suite` field. Every caller of
  `LoopState(...)` supplies one; the only in-tree caller
  (`tests/property/test_loop_termination.py`) is updated accordingly.
- The Rootknot schema extension in module_06 references
  `AcceptanceSuite.digest()` via a future `acceptance_suite_digest`
  field. The digest is stable across serialization round-trips
  (verified in tests) so it is safe to embed in signed artifacts.

## Alternatives Considered

- **Model-graded milestone oracle only (v0.3 baseline).** Rejected. The
  same model grades its own output; there is no independent authority.
  This is the failure mode the substrate rebuild exists to correct.
- **Single-scalar reward model.** Rejected. A single opaque scalar
  provides no failure attribution (which predicate failed, and why) and
  no reviewer-legible artifact. The suite exists precisely so that "why
  did the loop halt" is answerable off disk without re-running the model.
- **Post-hoc test generation during the loop.** Rejected. Any mechanism
  that lets the model add tests mid-loop lets it weaken its own exit
  condition. The compile-before-loop rule closes that door: the compiler
  proposes new tests only through the pre-loop handshake path, and the
  suite is frozen once the loop begins.
- **Optional suite (opt-in per run).** Rejected. Making the suite
  optional would leave the v0.3 model-graded path as the default, and
  the substrate signal 2 would remain PARTIAL. `LoopState` requires the
  suite as a construction-time field; there is no path around it.

## References

- `src/ract/core/predicate.py` — `AcceptancePredicate`, `AcceptanceSuite`,
  `PredicateResult`, canonical serialization, version-dispatched reader.
- `src/ract/core/gates.py` — built-in evaluators for each invocation
  kind, all pure over `(invocation, snapshot)`.
- `src/ract/core/compile.py` — `IntentCompiler`, grouped-handshake flow
  (`CompiledPreview`), source discovery.
- `src/ract/core/loop.py` — `LoopState.suite`, `check_t1(suite,
  snapshot)`, `build_loop_state(..., run_dir=...)` persistence factory.
- `src/ract/run_reporter.py` — `render_acceptance_suite` projection.
- `docs/ARCHITECTURE.md` — section "Acceptance suite compiled before
  loop entry."
- `docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` §2 (Substrate Layer 1) and §11
  signals 1 and 2.
- ADR-0003 (milestone-driven recursion) — the v0.3 baseline this ADR
  supersedes for T1; ADR-0003 remains the reference for how milestones
  drive scheduling.
- ADR-0006 (deferred-approval handshakes) — the mechanism used to gate
  proposed predicate groups.
- ADR-0008 (`ract.yaml` versioning) — the version-dispatch policy this
  ADR reuses for the compiled-suite format.
