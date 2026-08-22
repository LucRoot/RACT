# ADR-0044 -- LeWM 23-dim drift detection deferred to v0.6

## Status

Accepted 2026-08-21. Authored under the v0.5.1 spec-completeness
pipeline (`docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`, module_01).
Supersedes the implicit "will land in v0.5.x" reading of the
Memory Discipline spec's §Self-Adjustment Mechanisms item 4
(drift detection).

## Context

The Memory Discipline spec
(`docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`) v0.6-backlog line 72
names a "**Drift detector (23-dimensional behavioral vectors,
statistical process control on weekly distributions)**" as one of
the four self-adjustment mechanisms the spec is designed to feed.
The mechanism is referred to internally as **LeWM** (a shorthand
adopted during spec drafting for "**L**ightweight **e**mbedded
**W**orkload **M**etrics" — a 23-dimension per-invocation vector
capturing input-token profile, output-token profile, tool-call
mix, retrieval-cascade level, timing bands, and predicate outcomes,
compared across sliding windows via SPC control limits to raise a
drift alert when a week-over-week distribution shifts beyond
±3 sigma).

The 2026-08-21 source-spec audit
(`_BUILD/audit_2026-08-21c/lens_1F_self_adjustment.md` §4) verified
concretely that **no LeWM surface exists in the tree**:

- No `src/ract/observability/` package.
- No `lewm.py`, `drift.py`, `spc.py`, or `behavioral_vector.py`
  module anywhere under `src/`.
- Zero source hits for `lewm`, `LeWM`, `23-dim`, or "behavioral
  vector" in `src/ract/`.
- No SPC (statistical process control) detector.
- No week-over-week distribution comparator.
- No drift-alert event emitter (the spec's Operational Metrics
  section names "LeWM vector delta" as an emit field, but no code
  computes the vector).

Trace infrastructure exists (`src/ract/trace/writer.py`,
`events.py`) and could carry a `drift.detected` event kind, but the
vector, the SPC statistics harness, the alert path, and the
baseline data collection are all absent.

The gap this ADR closes is **release-label honesty**: v0.5.1's
consumer-facing docs must not read as if drift detection shipped.

## Decision

Defer LeWM 23-dim drift detection to v0.6. Ship v0.5.1 with the
substrate the mechanism will consume (event trace, JCS canonical
hashing, per-repo capability record, per-repo fingerprint,
failure-record aggregation) but without the mechanism itself.
Every consumer-facing surface must describe the deferral explicitly:

- `CHANGELOG.md` `[0.5.1]` section carries a
  "Not yet shipped in v0.5.1 (deferred to v0.6)" bullet naming
  LeWM 23-dim drift detection with this ADR reference.
- `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` v0.6-backlog bullet
  for the drift detector is annotated with a
  `[not shipped in v0.5.1 -- see ADR-0044]` callout.
- `docs/ROADMAP.md` gains a v0.6 backlog entry for LeWM drift
  detection cross-referencing this ADR.
- A grep-gate in `tests/test_release_surface.py` refuses any bare
  "LeWM" / "23-dim" mention in the `[0.5.1]` CHANGELOG section
  (allowlist: mentions that occur within a "Not yet shipped" /
  "deferred to v0.6" / "ADR-0044" context).

## Rationale

Implementing LeWM 23-dim drift detection at v0.5.1 would require,
at minimum:

1. **Define the 23-dimension behavioral vector schema.** The spec
   is deliberately underspecified on which 23 dimensions to
   choose; a vector schema ADR + closed-vocabulary enum + JCS-
   canonical serialisation would land first.
2. **Per-invocation vector computation.** A collector in
   `LoopController` / `SubstrateLoop` that emits the 23-dim vector
   for every completed step, joined against retrieval bundle,
   predicate outcomes, and timing.
3. **Baseline data collection.** SPC control limits (±3 sigma)
   require a per-repo baseline — typically 20+ weeks of steady-state
   data before the detector runs meaningfully. A v0.5.1 detector
   would either false-alarm on cold start or wait months before
   raising anything.
4. **SPC statistics harness.** Running mean, running variance,
   Welford's algorithm or equivalent, per-dimension control limits,
   multi-dimensional composite test (Hotelling T-squared or a
   dimension-wise vote).
5. **Sliding-window comparator.** Week-over-week distribution shift
   detection with drift-alert emission when any dimension crosses
   the SPC control limit.
6. **Drift-alert event integration.** A new `EventKind.drift.detected`
   entry in the closed vocabulary, wired into the alert surface
   (initially a JSONL sink at `.rack/drift/alerts.jsonl`; the
   spec is not prescriptive on the operator-notification path).
7. **Operator ceremony.** A `ract memory drift-review` verb
   listing recent alerts and letting the operator accept, dismiss,
   or annotate each.

That is multi-week work with a critical dependency on baseline
data collection that a fresh release cannot short-circuit. The
v0.5.1 spec-completeness pipeline's operator directive is
"get it right", not "implement drift detection now"; the audit
surfaced the release-label honesty gap, not a capability-blocking
gap.

## Alternatives considered

1. **Implement LeWM 23-dim drift detection in this pipeline.**
   Rejected. Cost is multi-week; scope is not what the operator
   directive names; baseline-data requirement means a v0.5.1
   detector would run without meaningful signal for weeks or
   months regardless.
2. **Remove drift detection from the spec entirely.** Rejected.
   The Memory Discipline spec names drift detection as one of
   four self-adjustment mechanisms; deletion would erase the
   intent that shapes the shipped trace + capability substrate.
   Deferral preserves the intent.
3. **Fake the claim.** Rejected on principle. The operator
   directive forbids false-claim laundering.
4. **Ship a stub `lewm.py` that computes a 23-dim vector without
   the SPC harness or alert path.** Rejected. A vector without
   the detector is dead data; downstream tooling would depend on
   the vector's shape, complicating the v0.6 real design decisions
   about which 23 dimensions to pick.
5. **Ship a simpler drift heuristic** (e.g., moving-average
   comparison on a small handful of aggregate metrics). Rejected
   for v0.5.1. A different-shape detector is not what the spec
   names; shipping "drift detection" whose mechanism differs from
   the spec would create the same release-label honesty gap this
   ADR closes, one abstraction level up. If a lighter detector is
   desirable, it should be authored in its own ADR under a
   different name, not passed off as the LeWM mechanism.
6. **Adopt an external SPC library** (e.g., `spc-chart`,
   `pyspc`). Rejected for v0.5.1. Dependency-cost problem plus
   the primary work (23-dim schema definition, baseline collection,
   integration) is still ahead of the library selection.

## Consequences

- **v0.5.1 does not ship LeWM behavioral vectors, an SPC detector,
  a sliding-window comparator, drift alerts, or an operator-review
  ceremony.** The substrate the mechanism will consume
  (event trace, per-repo capability record, per-repo fingerprint,
  failure-record aggregation) is production-live; the mechanism
  itself is v0.6 scope.
- The Memory Discipline spec's §Self-Adjustment "drift detection"
  item is now formally scoped to v0.6 by ADR reference, not merely
  by v0.6-backlog list. Readers tracing from spec to code find the
  ADR before the disappointment.
- The CHANGELOG grep-gate makes silent "LeWM shipped in v0.5.1"
  drift structurally impossible.
- **Reopens when v0.6 pipeline includes drift-detection adoption.**
  At that point this ADR gets a "Superseded by ADR-XXXX" header
  and the Status flips.

## References

- Memory Discipline spec: `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`
  v0.6-backlog line 72 (drift detector);
  §Self-Adjustment Mechanisms; §Operational Metrics ("LeWM vector
  delta" emit field).
- Source-spec audit finding:
  `_BUILD/audit_2026-08-21c/lens_1F_self_adjustment.md` §4
  ("Drift Detection -- NOT IMPLEMENTED").
- Audit summary top-10 must-fix #5:
  `_BUILD/audit_2026-08-21c/AUDIT_SUMMARY_c.md`.
- Spec-completeness pipeline: `docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`
  §4 module_01 brief.
- Companion deferral ADR (DSPy compilation-recompilation): ADR-0043.
- CHANGELOG `[0.5.1]` "Not yet shipped in v0.5.1 (deferred to v0.6)"
  section.
- Test gate:
  `tests/test_release_surface.py::test_no_false_lewm_claim_in_v0_5_1_changelog`.

## Flagged gaps (v0.6+)

- The v0.6 drift-detection pipeline needs its own ADR pinning
  the 23-dimension schema. The name "LeWM" is currently a
  shorthand; the schema ADR should either canonize it or replace
  it.
- Baseline-data cold-start problem: the v0.6 pipeline should
  either ship a rolling-baseline "bootstrapping" mode that raises
  no alerts for the first N weeks, or fold in cross-repo baseline
  transfer with explicit privacy guardrails.
- The spec's Operational Metrics "LeWM vector delta" emit field
  currently names a mechanism that does not compute the vector;
  the v0.6 pipeline should either implement the emit or drop the
  field.
- Composite-drift alerting (multi-dimension shift below per-dim
  SPC limits but above a Hotelling T-squared composite threshold)
  is a common SPC blind spot; the v0.6 detector design should
  address it directly.
