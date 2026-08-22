# ADR-0043 -- DSPy signature compilation-recompilation deferred to v0.6

## Status

Accepted 2026-08-21. Authored under the v0.5.1 spec-completeness
pipeline (`docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`, module_01).
Supersedes the implicit "will land in v0.5.x" reading of the
Memory Discipline spec's §Self-Adjustment Mechanisms item 3.

## Context

The Memory Discipline spec
(`docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`) lists four
self-adjustment mechanisms:

1. Quality probes (needle / coherence / adherence).
2. Failure-learning aggregation with narrowing-only invariant.
3. **DSPy signature compilation-recompilation with weekly recompile
   and diff report.**
4. LeWM 23-dim behavioral-vector drift detection (see ADR-0044).
5. Repo fingerprint.

Items 1, 2, and 5 shipped in v0.5.0 and were wired into production
paths in the v0.5.1 wiring-completion pipeline. **Item 3 did not
ship.** The 2026-08-21 source-spec audit
(`_BUILD/audit_2026-08-21c/lens_1F_self_adjustment.md`) verified
this concretely:

- No `src/ract/compilation/` directory exists.
- No `signatures.py` module.
- No `training.py` module.
- No trace-driven recompilation harness, no diff report emitter, no
  eval-score delta channel.
- **The `dspy` dependency is not present in `pyproject.toml`** — not
  in `[project].dependencies`, not in any `[project.optional-dependencies]`
  group, not in `[tool.poetry.dev-dependencies]`. The only surface
  mentions of "DSPy" are historical (this ADR, the Memory Discipline
  spec's v0.6 backlog list, one line of the spec's Ecosystem-drift
  note calling out the deferral explicitly).

The Memory Discipline spec's line 559 already names DSPy as v0.6
scope in the Ecosystem-drift section. The spec's v0.6 backlog
(line 70) already lists "DSPy signature compilation with weekly
recompile and diff report." The gap this ADR closes is
**release-label honesty across the doc corpus**: v0.5.1's CHANGELOG
and other consumer-facing docs must not read as if the mechanism
shipped.

## Decision

Defer DSPy signature compilation-recompilation to v0.6. Ship v0.5.1
with the substrate the mechanism will consume (probes, failure
records, repo fingerprint, JCS canonical hashing, event trace) but
without the mechanism itself. Every consumer-facing surface must
describe the deferral explicitly rather than imply the mechanism is
present:

- `CHANGELOG.md` `[0.5.1]` section carries a
  "Not yet shipped in v0.5.1 (deferred to v0.6)" bullet naming DSPy
  compilation with this ADR reference.
- `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` v0.6-backlog bullet
  for DSPy is annotated with a `[not shipped in v0.5.1 -- see
  ADR-0043]` callout.
- `docs/ROADMAP.md` gains a v0.6 backlog entry for DSPy signature
  compilation cross-referencing this ADR.
- A grep-gate in `tests/test_release_surface.py` refuses any bare
  "DSPy" mention in the `[0.5.1]` CHANGELOG section (allowlist:
  mentions that occur within a "Not yet shipped" / "deferred to v0.6"
  / "ADR-0043" context).

## Rationale

Implementing DSPy signature compilation-recompilation at v0.5.1
would require, at minimum:

1. **Add `dspy-ai` as a project dependency.** Non-trivial: DSPy pulls
   a heavy transitive stack (litellm, openai, pandas, joblib, tqdm),
   several of which the current pyproject deliberately avoids. Each
   would need Windows ARM64 wheel verification.
2. **Author DSPy signatures for the four v0.5.0 memory-discipline
   functions** (`intake`, `research`, `plan`, `edit`). Each signature
   is not a mechanical translation of the current prompt file; the
   spec requires input/output field typing that today's
   `functions/prompts/*.md` do not carry.
3. **Compile pipeline** — a `weekly_recompile.py` or equivalent
   scheduler that reads trace data from `.rack/failures/records.jsonl`
   + `evals/runs/*/`, runs DSPy's compile pass against a held-out
   evaluation set, and produces (signature diff, eval-score delta)
   pairs.
4. **Evaluation harness** — a small suite that scores baseline vs
   recompiled signatures on the same problems; the substrate for this
   partially exists in `evals/` but the DSPy-signature-vs-signature
   comparator does not.
5. **Diff report emitter** — a stable projection over the compile
   pass's per-signature deltas suitable for operator review; the
   spec is not prescriptive here so shape work is required.
6. **Operator ceremony** — a `ract memory recompile --review` verb
   allowing the operator to accept or reject the recompiled
   signatures before they replace the shipped prompts.

That is multiple weeks of work. The v0.5.1 spec-completeness
pipeline's operator directive is "get it right", not "implement DSPy
now"; the audit surfaced the release-label honesty gap, not a
capability-blocking gap. The v0.5.0 Memory Discipline pipeline's
own §Bar-policy note ("v0.5.0 ships the substrate DSPy sits on but
does not ship DSPy itself") already anticipated this deferral; this
ADR pins it into the v0.5.1 release-label surface so no consumer
reads the substrate as the mechanism.

## Alternatives considered

1. **Implement DSPy compilation-recompilation in this pipeline.**
   Rejected. Cost is multi-week; scope is not what the operator
   directive names ("close the audit's docs-honesty gap"); adding
   the dependency + signatures + compile pass + eval harness + diff
   report + operator ceremony expands the v0.5.1 release surface
   substantially. The audit does not blame missing DSPy for any
   runtime failure; it blames the docs for implying it shipped.
2. **Remove DSPy from the spec entirely.** Rejected. The Memory
   Discipline spec is prescriptive: it names the four self-adjustment
   mechanisms the substrate is designed to feed. Deletion would
   erase the intent that motivates the shipped substrate (probes,
   failure records, repo fingerprint). Deferral preserves the intent
   and pins the honest current status.
3. **Fake the claim** (leave the CHANGELOG as-is, hoping no reader
   verifies against source). Rejected on principle. The operator
   directive ("no false-claim laundering, no partial fixes that
   read as complete") makes this a hard non-option; this ADR exists
   precisely to prevent it.
4. **Ship a stub compilation module that always returns
   "no-op / not implemented".** Rejected. A stub that emits a
   deferral warning is a runtime lie in slightly different packaging;
   it also invites downstream code to depend on the stub's shape,
   making the v0.6 real implementation harder. A missing surface
   is honest; a stub surface is a maintenance liability.
5. **Adopt a non-DSPy compilation library** (e.g., LangChain's
   `compile`, TextGrad, in-house). Rejected for v0.5.1. Selection
   would require its own trade-off analysis and would land the same
   dependency-cost problem as (1) without the DSPy ecosystem's
   maturity around signature compilation.

## Consequences

- **v0.5.1 does not ship a DSPy dependency, signatures, compile
  pipeline, diff report, or operator-review ceremony for
  signature recompilation.** The substrate the mechanism will consume
  is production-live (probes, failure records with narrowing
  invariant, repo fingerprint, JCS canonical hashing, JsonlEventWriter);
  the mechanism itself is v0.6 scope.
- The Memory Discipline spec's §Self-Adjustment "compilation
  recompilation" item is now formally scoped to v0.6 by ADR
  reference, not merely by ecosystem-drift note. Any future
  reader tracing from spec to code will find the ADR before
  the disappointment.
- The CHANGELOG grep-gate makes silent "DSPy shipped in v0.5.1"
  drift structurally impossible. A future author who edits the
  CHANGELOG to claim the mechanism ships without editing the code
  and this ADR gets a test failure at CI.
- **Reopens when v0.6 pipeline includes DSPy adoption.** At that
  point this ADR gets a "Superseded by ADR-XXXX" header and the
  Status flips.

## References

- Memory Discipline spec: `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`
  §Self-Adjustment Mechanisms item 3, v0.6-backlog line 70,
  Ecosystem-drift line 559.
- Source-spec audit finding:
  `_BUILD/audit_2026-08-21c/lens_1F_self_adjustment.md` §3
  ("Compilation Recompilation -- NOT IMPLEMENTED").
- Audit summary top-10 must-fix #4:
  `_BUILD/audit_2026-08-21c/AUDIT_SUMMARY_c.md`.
- Spec-completeness pipeline: `docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`
  §4 module_01 brief.
- Companion deferral ADR (LeWM 23-dim drift detection): ADR-0044.
- CHANGELOG `[0.5.1]` "Not yet shipped in v0.5.1 (deferred to v0.6)"
  section.
- Test gate:
  `tests/test_release_surface.py::test_no_false_dspy_claim_in_v0_5_1_changelog`.

## Flagged gaps (v0.6+)

- The v0.6 pipeline that ships DSPy compilation should re-verify
  that `functions/prompts/*.md` (currently free-text prompts) either
  become DSPy signatures directly or acquire input/output typing
  that the compiler can consume without prompt rewrites.
- A per-repo capability record already exists
  (`.rack/probes/capability.json`); the compilation pipeline will
  need a companion `signature_version` record so recompiles can be
  attested against the capability snapshot they trained on.
- The operator-review ceremony is spec-underspecified; the v0.6
  pipeline should author its own ADR pinning the recompile-review
  contract before the mechanism goes live.
