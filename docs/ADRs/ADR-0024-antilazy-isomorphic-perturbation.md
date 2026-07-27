# ADR-0024 — Isomorphic perturbation gate for rule-like intents

Status: accepted (v0.4.0-rc1, ALM pipeline module_06).

## Context

The substrate (SUBSTRATE §2, module_01) compiles an intent into an
`AcceptanceSuite` the environment then verifies. ALM adds Gate G1
(held-out predicates, module_01), G3 (patch differentiation, module_02),
G5 (test integrity, module_03), G7 (companion red team, module_04), and
Invariant AL-1 (three-signature Rootknot, module_05). Each of these
guards a specific failure mode but none of them observes the shape of
the solution under transformations of the intent.

ALM §9 (Isomorphic Perturbation for Rule-Like Intents) names one
remaining failure mode: for intents that express a rule ("every user
must have exactly one primary email"; "no function may bypass the audit
logger"; "all monetary values are stored as integer cents") a model
that pattern-matches surface vocabulary can pass every other gate and
still produce a solution that would collapse if the intent used
different words for the same rule. The classical signal in the
Isomorphic Perturbation Testing literature is: restate the intent under
isomorphic transformations and re-check the solution shape; genuine
rule induction is invariant, shortcut solutions diverge.

The gate is optional. It fires only when a compile-time detector flags
the intent as rule-like. Non-rule-like intents (open-ended refactors,
"add a feature", investigative tasks) do not benefit from the check;
running it unconditionally would waste primary-provider dispatch on
every completion.

## Decision

1. Add `src/ract/antilazy/iso_perturb.py` with:
   - `RuleLikeDetection` — the detector output; carries a
     `confidence` score in [0.0, 1.0] so callers can dial the
     transformation count (lateral chain branch A).
   - `detect_rule_like_intent(intent)` — a stdlib-regex detector
     over the universal-quantifier keywords (`every`, `all`, `no `,
     `exactly one`) and the modal keywords (`must`, `never`,
     `always`, `cannot`). Deliberately over-inclusive; the caller
     compensates via the confidence score.
   - `IsomorphicTransformation` and `transform_intent(intent, *,
     workspace_symbols)` — three variants (`rename_entities`,
     `swap_syntax`, `permute_examples`) generated deterministically
     from a fixed synonym table (stdlib only, no Faker dependency).
     Identifiers appearing in `workspace_symbols` pass through the
     rename unchanged (lateral chain branch B).
   - `compare_solutions(original, transformed, *, transformation)` —
     AST-normalized comparison with the transformation's renaming map
     applied in reverse; falls back to `difflib.SequenceMatcher.ratio`
     when either solution is not parseable Python (lateral chain
     branch C).
   - `run_iso_perturbation(...)` — dispatches each transformed intent
     to the primary via a `SolutionProducer` protocol and returns a
     `PerturbationDivergenceReport`.
   - `run_iso_perturb_gate(...)` — the loop-side wrapper; runs the
     detector, decides whether to fire, writes the report to
     `evals/runs/<run_id>/iso_perturb.json`, and returns an
     `IsoPerturbGateOutcome` the loop reads to decide whether to
     block COMPLETE.
2. Extend `IntentCompiler` with `compile_and_detect_rule_like` so
   ALM callers can retrieve `(suite, rule_like)` in one pass without
   re-parsing the intent.
3. Wire the gate into `LoopController` via an optional
   `iso_perturb: IsoPerturbBundle | None` constructor kwarg. When
   `None` the loop runs the substrate + module_04 paths unchanged.
   When present, the gate runs after the module_04 completion gates
   and blocks COMPLETE on divergence.
4. Divergence emits `laziness.violated` with
   `kind="isomorphic_divergence"` (a new value under the existing
   `laziness.violated` event kind, so no `LEGAL_EVENT_KINDS`
   schema bump is required).

## Rejected alternatives

- **Always-on gate.** Rejected. The gate is over-inclusive by design
  in the detector; running it on non-rule-like intents (open-ended
  refactors, investigative tasks) wastes at least one primary-provider
  dispatch per transformation on completions where the divergence
  signal is meaningless. The optional-gate design lets the detector be
  aggressive about rule-like classification without paying dispatch
  cost on false positives.
- **Model-based rule-like detection.** Rejected. Asking the primary
  provider to classify its own intent as rule-like grades its own
  homework: a primary that pattern-matches the intent will also
  pattern-match "is this a rule-like intent?" toward the safe answer.
  A deterministic keyword-plus-regex detector is opaque to the primary
  and produces the same classification for the same intent across
  runs.
- **Single transformation only.** Rejected. One transformation is too
  easy to survive by coincidence: a solution that hard-codes the word
  "audit_logger" and happens to be tested against a rename to
  "ledger_recorder" survives if either the rename or the model's
  response happens to preserve the wire vocabulary. Three
  transformations of orthogonal shape (rename, syntax, list-order)
  give the divergence signal three independent chances to fire.
- **String-similarity comparison instead of AST-normalized.**
  Rejected. String similarity would fail on the specific case the
  gate is designed to catch: a solution that is semantically
  identical but formatted differently (whitespace, comment
  differences, argument-name changes under the rename map). AST
  normalization plus the reverse-rename application produces the same
  digest for semantically identical solutions; string similarity is
  the fallback only when AST parsing fails on both sides.
- **Faker library for the rename synonyms.** Rejected. Introduces a
  runtime dependency for a purpose the stdlib handles adequately.
  The fixed synonym table is deterministic (digest-stable) and
  extensible without a version-pin dance; every synonym pair is
  documented in the source and reviewed in code review.

## Interaction with G1 (held-out suite) — lateral chain branch D

G1 verifies the specific solution passes the held-out predicates the
composer wrote. Iso-perturbation verifies the solution's SHAPE is
invariant under transformation of the intent. These are different
questions: G1 catches a solution that passes the visible predicates by
leaking through the visible-predicate boundary; iso-perturbation
catches a solution that passes both halves by pattern-matching to the
intent's surface vocabulary. Both run when the intent is rule-like;
the gates are orthogonal and the joint requirement raises the bar past
either alone.

## Consequences

- The gate is opt-in per LoopController construction. Substrate CLI
  paths and v0.3 callers are unchanged.
- The DoD writes the report on every rule-like completion, so audits
  can retrospectively assess how often divergence fires and against
  which transformation.
- Second Pass adversarial questions (module_06.md `## Second Pass
  discipline`) list four attack shapes; the module carries three of
  them in Flagged gaps and closes one (the rename map preserves
  workspace symbols by construction, branch B). See `## Second Pass
  results` in `_BUILD/ract_v0.4.0_antilazy/module_06.md` for the
  reviewer's shipped findings.

## Follow-ups (v0.5 scope)

- Cost cap on the primary-provider dispatch per rule-like completion
  (lateral chain branch E, deferred). Belongs in `ract.yaml` config.
- Cross-language solution comparison (currently Python only).
- Anomaly-detection on the free-variable count in intents (Second
  Pass Q1 defence: an intent whose free-variable count is anomalously
  low relative to token count is a candidate for rename-escape).

## References

- ALM master spec §9 (Isomorphic Perturbation for Rule-Like Intents).
- SUBSTRATE §2.4 (`IntentCompiler`).
- ALM ADR-0019 (module_01 held-out suite).
- ALM ADR-0022 (module_04 companion + effort reconciliation).
- Python `ast` module (stdlib).
- `_BUILD/ract_v0.4.0_antilazy/module_06.md` — the module fragment.
