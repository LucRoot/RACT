# ADR-0020 — Semantic patch differentiation and coverage delta as pre-commit gates

## Status

Accepted (v0.4.0-rc1, ALM module_02).

## Context

Substrate module_01 (ADR-0010) plus ALM module_01 (ADR-0019) landed
the compiled ``AcceptanceSuite`` and its dual visible-plus-held-out
extension. Two failure modes those gates still admit:

1. **Semantic no-op patches** — a diff passes the visible suite while
   being behaviorally indistinguishable from doing nothing. UTBoost
   measured over 5% of SWE-bench Verified instances as this shape.
2. **Solution leakage** — a diff byte-matches a commit in git history
   or an entry in the retrieval index; the model surfaced training-
   corpus material rather than authoring the change. SWE-Bench+
   measured 32.67% leakage on the base corpus.

ALM spec §3.3 (Gate G3) and §3.4 (Gate G4) close both by adding two
pre-commit checks that fire from ``StepTransaction``'s post-condition
set.

Reference sources:

- ALM spec §3.3 (Gate G3), §3.4 (Gate G4); §13 signals 3 and 4.
- PatchDiff (companion-generated differential tests). Public paper.
- UTBoost (5% no-op measurement). Public paper.
- SWE-Bench+ (32.67% leakage measurement). Public paper.
- ``coverage.py`` measurement library: ``https://coverage.readthedocs.io/``.
- ``pytest-cov`` runner: ``https://github.com/pytest-dev/pytest-cov``.

## Decision

Accept both gates as pre-commit enforcement on top of the substrate
transaction.

1. **Patch differentiation (G3).** ``run_patchdiff(patch, workspace,
   generator, runner, baseline_kind="null")`` asks a companion-shaped
   ``DifferentiatorGenerator`` for pytest-format tests targeting the
   functions the diff touches. The runner filters each candidate
   through a three-run flakiness check (drop if outcomes disagree) and
   keeps only tests whose verdict differs between ``patch`` and the
   baseline. A diff that touched functions but produced zero surviving
   differentiators is marked ``is_semantic_noop=True`` and rolls back
   with ``kind="semantic_noop"``.

2. **Total differentiator budget (lateral chain branch A).** The
   generator allocates a total budget (default 30) across touched
   functions with proportional allocation, capped per function at the
   PatchDiff-stated maximum of 10. A diff touching 40 functions
   receives one shot per function; the second-pass reviewer flagged
   this as a possible degeneration and it is recorded in Flagged gaps.

3. **Leakage fingerprint (lateral chain branch B, E).** For every
   hunk that clears the 5-line / 100-char floor, ``check_leakage``
   fingerprints the hunk (SHA-256 over the newline-joined added
   lines), searches git history with ``git log --all -S`` against the
   first non-empty added line, and queries the optional
   ``RetrievalIndex``. A match at either channel surfaces as a ref in
   ``leakage_matches``. Hunks below the floor count as
   ``leakage_below_floor``. When the retrieval index is absent, the
   report marks ``retrieval_index_absent=True`` so the reviewer sees
   what evidence the scan actually consulted (branch E).

4. **Coverage delta (G4).** ``run_coverage_delta(parent, child, patch,
   mutation_report_parent, mutation_report_child)`` computes
   ``lines_new = added_lines - moved_lines`` (branch C: a pure
   refactor moves lines rather than adding them, so it does not
   inflate the denominator), reads ``coverage.<path>`` metadata from
   the child snapshot to count covered new lines, and returns
   ``coverage_ratio``. Below ``tau_cov = 0.8`` rolls back with
   ``kind="coverage_delta_insufficient"``. For non-trivial changes the
   mutation-coverage delta between child and parent reports must
   exceed ``delta_mut = 0.1``.

5. **Trivial-change bypass.** ``_classify_triviality`` marks a diff
   trivial iff the substantive added-line count is at or below 2 and
   every substantive added line has a whitespace-normalized match in
   the removed lines (a pure reformat) or the substantive added-line
   count is zero. A trivial change skips the mutation-delta check.
   The Second Pass adversarial question 2 flags this as gameable across
   steps — a model that splits a substantive change across steps so
   each looks trivial defeats the per-step check. That cross-step
   attack is a Flagged gap.

6. **Non-Python files.** The runner logs non-Python touched files
   under ``non_python_files`` in the report and does not measure
   coverage for them. Extension to Rust/TypeScript is v0.5 backlog.

## Consequences

- ``StepTransaction.post_conditions`` gains two new gate helpers
  (``enforce_g3``, ``enforce_g4``). They live in
  ``ract.antilazy.pre_commit`` alongside ``enforce_g2``; substrate
  callers that never touch the antilazy layer observe no change.
- ``ract.trace.events.EventKind`` gains no new value — G3 and G4 both
  emit under the existing ``laziness.violated`` and
  ``predicate.evaluated`` vocabulary (with new ``kind`` payload
  discriminators ``semantic_noop``, ``solution_leakage``,
  ``coverage_delta_insufficient``, and ``coverage_delta``).
- No new runtime dependency. ``coverage.py`` and ``pytest-cov`` are
  already dev extras from substrate module_01's ``[dev]`` group; G4
  reads coverage metadata off the snapshot rather than invoking
  coverage.py in-process, so the runtime import is not required.

## Rejected alternatives

1. **Fuzz-based differentiation only.** Random input generation
   without semantic direction.
   *Rejected.* The Meta-flavored PatchDiff design explicitly asks for
   companion-directed tests because random fuzz misses the surface a
   targeted differentiator hits. Zero differentiators is a stronger
   signal than "no fuzz input crashed".

2. **Coverage delta at CI time only.** Skip G4 pre-commit; run
   coverage nightly instead.
   *Rejected.* The ALM premise is that laziness fires pre-commit so
   the operator never has to reconstitute why a merged commit later
   fails the delta. Nightly CI is the reporting layer; the gate is
   pre-commit.

3. **Leakage check by string match only.** Skip the fingerprint step
   and just search git history for the raw hunk text.
   *Rejected.* Whitespace / formatter differences at commit time
   silently defeat pure string match. The rolling-hash fingerprint
   over normalized lines is what makes the check robust. A shuffle-
   then-rename attack still defeats both raw string match and the
   fingerprint; that harder attack is a Flagged gap and requires a
   secondary AST-normalized fingerprint that is v0.5 work.

4. **Mutation-delta as a soft advisory.** Report the delta but do not
   gate the commit on it.
   *Rejected.* The whole ALM premise is environment-authored refusal;
   surfacing a number the model can ignore is theatre.

5. **Per-intent ``tau_cov`` override via ``ract.yaml``.**
   *Deferred to hardening.* The ALM spec pins 0.8 as the default;
   per-intent overrides land in a later pipeline. Flagged for
   follow-up in module_02's ``Flagged gaps``.

## Migration

None. This ADR adds two new gates; nothing existing changes shape.
Substrate callers that never construct a ``Patch`` or invoke
``enforce_g3`` / ``enforce_g4`` observe the substrate behaviour
unchanged.


# RACT 0.4.0
