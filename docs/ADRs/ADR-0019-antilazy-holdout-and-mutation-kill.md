# ADR-0019 — Dual acceptance suite with sandbox-key-sealed held-out half and mutation-kill threshold as pre-commit gates

## Status

Accepted (v0.4.0-rc1, ALM module_01).

## Context

Substrate module_01 (ADR-0010) landed the compiled ``AcceptanceSuite``
as T1's exit condition: the environment decides when a run is done, not
the model. ALM spec §3.1 and §3.2 push the design one turn further.
Even with a suite the environment enforces, a model that observes which
predicates the suite contains can steer its patch to satisfy them
literally while missing the underlying intent — this is the "model
grades its own homework" failure mode restated at the suite level. The
ALM answer is a **dual acceptance suite**: a visible half the model
sees and a held-out half the environment enforces without exposing.

Gate G1 (§3.1) is that split plus a non-triviality check: a composed
held-out suite is worthless if it evaluates identically to the visible
suite. Gate G2 (§3.2) closes the mutation-testing loop: after the model
claims completion, mutation testing runs against the touched surface;
below a 0.7 kill threshold, the pre-commit gate rolls back and surfaces
surviving mutants as counterexamples for the next iteration.

Reference sources:

- ALM spec §3.1 (Gate G1: Held-Out Predicate Enforcement) and §3.2
  (Gate G2: Mutation-Kill Threshold); §13 signals 1 and 2.
- SUBSTRATE spec §2 (Compiled Acceptance Predicates); §7.1
  (SandboxKey attestation).
- SpecBench (visible-plus-held-out validation split). Public paper.
- `mutmut` Python mutation-testing library:
  `https://github.com/boxed/mutmut`.
- Stryker mutation-testing framework (per-mutant test-set
  restriction): `https://stryker-mutator.io/`.
- Meta ACH (LLM-based Equivalence Detector, 0.79 precision). Public
  Meta engineering post.
- `cryptography` Python library (AES-256-GCM):
  `https://cryptography.io/`.

## Decision

Accept both gates as pre-commit enforcement on top of the substrate
suite.

1. **Dual acceptance suite.** ``IntentCompiler.compile`` accepts an
   optional ``companion: HoldoutComposer``. With a companion, the
   compiler returns a ``DualAcceptanceSuite`` wrapping the substrate
   ``AcceptanceSuite`` as its ``visible`` half plus a composed
   ``held_out`` half whose canonical bytes are AES-256-GCM sealed
   under a symmetric key derived from the run's ``SandboxKey`` via
   HKDF-SHA256. The public ``held_out_digest`` is committed alongside
   the seal so an auditor can prove which suite was enforced without
   reading the plaintext.

2. **Non-triviality check (lateral chain branch E).** A held-out suite
   whose predicates evaluate identically on the current workspace and
   on a deterministic byte-shuffled perturbation of the touched surface
   is marked ``holdout_kind="trivial"`` and treated as auto-pass by
   T1. This closes the escape hatch where a composer returns a suite
   the model can trivially satisfy.

3. **T1 evaluates both halves.** ``check_t1`` duck-types the dual
   suite through a ``visible``/``held_out`` attribute pair and calls
   ``check_visible_and_held_out``, which fires ``laziness.violated``
   with ``kind="visible_holdout_gap"`` when the visible half is all-ok
   but the held-out half is not. Substrate T1 semantics are preserved
   for callers that hold a bare ``AcceptanceSuite``.

4. **G2 as pre-commit gate.** ``enforce_g2(transaction, suite, ...)``
   runs mutation testing against the touched surface, capped at
   ``DEFAULT_MUTANTS_PER_FILE_CAP=200`` per file with deterministic
   sampling (lateral chain branch B), and per-mutant timeout defaulting
   to 10s (a timeout lands as ``survived``, never ``equivalent``, so a
   hung evaluator cannot inflate the kill rate). Below the threshold
   the gate returns ``should_roll_back=True`` and emits
   ``laziness.violated`` with ``kind="mutation_kill_below_threshold"``.

5. **ACH-style equivalence detector.** ``filter_equivalent`` batches
   surviving mutants into groups of
   ``DEFAULT_EQUIVALENCE_BATCH_SIZE=10`` for one companion dispatch
   per batch (lateral chain branch C). A mutant flagged equivalent
   lands under ``mutants_equivalent`` and is subtracted from the
   kill-rate denominator, matching Meta's ACH design at 0.79
   precision.

## Consequences

- Substrate T1 (``ract.core.loop.check_t1``) grows a duck-typed dual
  branch. Callers that already pass a bare ``AcceptanceSuite``
  continue to work unchanged.
- ``IntentCompiler.compile`` grows a keyword argument. The return
  type widens to ``AcceptanceSuite | DualAcceptanceSuite``; callers
  that need the narrow return call ``compile_with_holdout``.
- ``ract.trace.events.EventKind`` gains one value:
  ``laziness.violated``. That is the only vocabulary change this ADR
  makes to the substrate trace.
- ``mutmut`` is a **dev-optional** dependency. The default synthetic
  source (``AstArithmeticMutantSource``) ships in the runtime so a
  fresh checkout without ``mutmut`` still runs G2 with a limited
  mutant vocabulary; the ``MutmutSource`` adapter raises a clear
  ``RuntimeError`` pointing at the dev extra when invoked without
  the library installed.

## Rejected alternatives

1. **Single suite with a hidden random subset.** The environment picks
   a random subset of the compiled suite to hide from the model.
   *Rejected.* The subset is chosen at run-open and leaks through the
   event trace (a predicate that never appears in the trace is a
   held-out predicate); a model that observes trace shape breaks the
   split. G1's HKDF-scoped seal is proof against trace observation.

2. **Model-graded held-out predicates.** A second LLM call at
   termination time asks the model whether the held-out claims hold.
   *Rejected.* Grades own homework at one remove. The composed
   predicates must be code the environment executes, not text the
   model interprets.

3. **Fixed 0.7 threshold without an equivalence filter.** Report the
   raw ``killed / total`` ratio.
   *Rejected.* An equivalent mutant is a false-negative signal
   (semantically indistinguishable from the original); counting it
   against the kill rate biases toward over-testing surface that
   cannot be behaviorally observed. Meta's ACH precision of 0.79 is
   the accepted floor.

4. **Mutation testing at CI time only.** Skip G2 pre-commit; run
   mutation nightly instead.
   *Rejected.* The pipeline's premise is that laziness fires
   pre-commit so the operator never has to reconstitute why the tag
   commit passed. Nightly CI is the reporting layer; the gate is
   pre-commit.

5. **Per-intent threshold configurability.** Let the operator set the
   G2 threshold per intent in ``ract.yaml``.
   *Deferred to hardening.* The ALM spec pins 0.7 as the default;
   per-run overrides land in a later pipeline. Flagged for follow-up
   in module_01's ``Flagged gaps``.

## Migration

None. This ADR adds a new capability; nothing existing changes shape.
Callers that never construct an ``IntentCompiler`` with a ``companion``
observe the substrate return type and the substrate T1 semantics.


# RACT 0.4.0
