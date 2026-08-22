# ADR-0045 -- Failure-learning nightly job + human-review queue + retrieval-strategy adjustment surface deferred to v0.6

## Status

Accepted 2026-08-22. Authored under the v0.5.1 spec-completeness
pipeline (`docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`, module_08).
Formalizes the cancellation of the original module_06 scope per the
Ox Alpha adversarial pipeline review 2026-08-21
(`_BUILD/ract_v0.5.1_spec_completeness/ox_alpha_reviews/pipeline_challenge_2026-08-21.md`
§1). Complements the deferral ADRs ADR-0043 (DSPy signature
compilation), ADR-0044 (LeWM 23-dim drift detection), and
ADR-0046 (Bonsai council model-based summarizer) — same shape, same
"honest-deferral over primitive-without-wiring" discipline.

## Context

The Memory Discipline spec
(`docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`) §Failure Learning
prescribes five behaviors:

1. Structured failure record capture per composition-runner phase.
2. Sliding-window aggregation with a narrowing-only proposal shape.
3. A **retrieval-strategy adjustment surface** — the aggregator does
   not only propose budget narrowings; it also proposes retrieval-
   strategy default changes (cache-TTL, neighborhood width, per-
   symbol target-token bumps) when specific failure classes fire
   above threshold.
4. A **human-review queue** — proposals surface in an operator-
   review buffer before landing as durable overrides.
5. A **nightly failure-learning job** — cron / scheduler cadence
   that runs the aggregator, populates the review queue, and emits
   a daily proposals summary event.

Items 1 and 2 shipped in v0.5.0 (`failure_records.FailureRecord` +
`aggregate` + `NarrowingProposal.__post_init__` narrowing-only
invariant + `validate_proposal_against_live_value()` live gate).
Items 3, 4, and 5 did not — the 2026-08-21 source-spec audit
(`_BUILD/audit_2026-08-21c/lens_1F_self_adjustment.md` findings 3
and 7, both MEDIUM) surfaced their absence. The v0.5.1 spec-
completeness pipeline originally scheduled all three under
module_06.

The Ox Alpha adversarial review dated 2026-08-21 (verbatim
`_BUILD/ract_v0.5.1_spec_completeness/ox_alpha_reviews/pipeline_challenge_2026-08-21.md`
§1) cancelled module_06 pre-build:

> **Cancel module_06.** It bundles three subsystems — a scheduled
> job, a human-review queue, and a retrieval-strategy adjustment
> surface — into one module for a *point release*. A human-review
> queue with no operator workflow is dead code on arrival. An
> "adjustment surface" with no retrieval-path reader is the
> primitive-without-wiring trap, pre-committed. ADR it to v0.6
> exactly like ADR-0043/0044. This also shrinks your highest-risk
> module out of existence before it can hurt you.

Three independently defensible primitives, one bundled module, and
no operator workflow to consume any of them make this the classic
residue pattern the Ox Alpha review names.

## Decision

Defer all three items to v0.6. Ship v0.5.1 with the aggregator + the
operator-triggered `ract memory apply-narrowings` CLI verb (v0.5.0
scope) unchanged. No new nightly scheduler, no new human-review
queue file, no new retrieval-strategy adjustment surface land in
v0.5.1.

Every consumer-facing surface names the deferral explicitly:

- `CHANGELOG.md` `[0.5.1]` — the "Not yet shipped in v0.5.1
  (deferred to v0.6)" section carries a bullet naming ADR-0045 as
  the deferral rationale for all three subsystems.
- `docs/ROADMAP.md` — v0.6 backlog entry for a nightly failure job +
  review queue + retrieval-strategy adjustment surface, cross-
  referencing this ADR.

## Rationale

Shipping any of the three items in v0.5.1 without shipping the
others is worse than shipping none:

1. **Human-review queue without an operator workflow is dead code.**
   The spec's item 4 assumes a reviewer sees a queue and either
   approves or rejects entries; RACT has no such reviewer surface,
   no CLI verb pair (list / approve / reject), no approval durability
   store, and no bidirectional path from approvals back to the
   `apply-narrowings` path. Adding the queue file with only the
   producer side wired would produce an ever-growing JSONL nobody
   reads.
2. **Retrieval-strategy adjustment surface without a reader in the
   retrieve path is the primitive-without-wiring trap.** The v0.5.1
   `retrieve()` primitive reads its defaults from
   `RetrievalDefaults` via `repo_fingerprint.retrieval_defaults_
   from_fingerprint()` (already only partially wired per lens_1F
   MEDIUM finding 5). Adding a second override surface with no
   reader would produce a `.ract/failures/retrieval_overrides.yaml`
   nobody consults.
3. **Nightly job without an operator surface for the produced
   artifacts is scheduled dead code.** A scheduler that runs the
   aggregator on a cadence but writes its output into a queue nobody
   reads and an overrides file nothing consumes is worse than a
   manual CLI — at least the manual CLI shows the operator the
   proposals before they are dropped on the floor.

Bundling the three into a single module compounds the risk. The
v0.5.1 spec-completeness pipeline's operator directive is "get it
right", not "invent three coupled subsystems for a point release".
Deferring to v0.6 keeps the substrate the mechanism will consume
(failure records, aggregator, narrowing invariant, live gate) fully
operational; v0.6 can land the three items as a coordinated
workflow with an operator surface.

## Alternatives considered

1. **Ship all three subsystems in v0.5.1 under a single module.**
   Rejected. Ox Alpha's adversarial review names this as the
   primitive-without-wiring trap; the operator surface a reviewer
   would use to interact with the queue does not exist and cannot
   land cleanly inside a point release. Shipping any of the three
   without the other two makes their absence louder, not quieter.
2. **Ship only the retrieval-strategy adjustment surface** (the
   smallest of the three) as a module_06 slim variant. Rejected on
   the same principle: without a reader in the retrieve path, the
   adjustment surface is orphan configuration.
3. **Ship the nightly job alone.** Rejected — the aggregator is
   already invocable via `ract memory apply-narrowings`; a scheduler
   that runs it on a cadence but has no queue for the output to land
   in and no adjustment reader is a schedule for dropping proposals
   on the floor.
4. **Delete the spec's items 3, 4, and 5.** Rejected. The gap is
   real — the Memory Discipline spec explicitly prescribes all
   three — but the fix belongs in v0.6 as a coordinated workflow,
   not in a point release as three uncoordinated primitives.
5. **Ship a review-queue file with no reviewer surface and mark it
   "operator can read manually".** Rejected as the JSONL-nobody-reads
   pattern; the audit that surfaced the gap would flag the same
   deferral pattern.

## Consequences

- **v0.5.1 does not ship a nightly failure-learning scheduler, a
  human-review queue file, a reviewer CLI surface, or a retrieval-
  strategy adjustment override reader.** The v0.5.0 aggregator and
  operator-triggered `ract memory apply-narrowings` CLI verb remain
  the sole path from failure records to budget overrides.
- **Substrate that a v0.6 pipeline will consume is production-live.**
  `FailureRecord` JSONL at `.ract/failures/records.jsonl` +
  `aggregate` + `NarrowingProposal.__post_init__` + live gate +
  `applied_narrowings.jsonl` audit trail all ship in v0.5.1. The
  v0.6 pipeline lands the review queue, the reviewer CLI surface,
  the retrieval-strategy adjustment reader, and the scheduler as a
  coordinated workflow on top of that substrate.
- **The Memory Discipline spec's §Failure Learning items 3-5 are
  now formally scoped to v0.6.** Items 1-2 shipped v0.5.0 and remain
  operational; items 3-5 defer via this ADR analogously to how
  ADR-0043 defers DSPy compilation-recompilation and ADR-0044
  defers LeWM drift detection.
- **The v0.5.1 spec-completeness pipeline shrinks from 8 to 7
  modules** (module_06 CANCELLED). module_07 and module_08 keep
  their numbers (renumbering would corrupt ledger provenance);
  module_08 gains the 4-vector re-audit hardening per Ox Alpha §3.
- **Reopens when v0.6 pipeline includes a failure-learning
  workflow.** At that point this ADR gets a "Superseded by ADR-XXXX"
  header and the Status flips.

## References

- Memory Discipline spec: `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`
  §Failure Learning items 3-5.
- Source-spec audit finding:
  `_BUILD/audit_2026-08-21c/lens_1F_self_adjustment.md` findings 3
  and 7 (MEDIUM severity).
- Ox Alpha adversarial review authorizing the cancellation:
  `_BUILD/ract_v0.5.1_spec_completeness/ox_alpha_reviews/pipeline_challenge_2026-08-21.md`
  §1.
- Spec-completeness pipeline: `docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`
  §4 module_06 (CANCELLED) + §4 module_08 (release close hosts this
  ADR).
- Companion deferral ADRs (same pattern): ADR-0043 (DSPy),
  ADR-0044 (LeWM), ADR-0046 (Bonsai council summarizer).
- Shipped substrate: `src/ract/memory/failure_records.py`
  (`FailureRecord`, `aggregate`, `NarrowingProposal`,
  `validate_proposal_against_live_value`,
  `append_applied_narrowing`); `src/ract/memory/cli_memory.py`
  (`ract memory apply-narrowings`).

## Flagged gaps (v0.6+)

- The v0.6 pipeline that ships the failure-learning workflow needs
  to land the three items as a coordinated workflow, not three
  independent primitives — the operator reviewer surface (CLI verb
  pair `list` / `approve` / `reject` + approval durability store)
  must land before or in the same module as the queue producer, and
  the retrieval-strategy adjustment reader must land in the
  `retrieve()` primitive in the same module as the override
  producer.
- The scheduler cadence choice (nightly cron on a Windows / POSIX
  cross-platform substrate) is out of scope for this ADR and should
  be addressed by the v0.6 pipeline's scheduler module. RACT today
  has no scheduler substrate; the v0.6 pipeline may either grow one
  or defer the scheduler to an operator-configured OS scheduler
  (Windows Task Scheduler / cron).
