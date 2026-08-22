# RACT v0.5.1 Spec-Completeness Spec

**Ships as:** v0.5.1 (third re-tag; supersedes `96b06790` wired-only version)
**Trigger:** Source-spec audit `_BUILD/audit_2026-08-21c/AUDIT_SUMMARY_c.md` surfaced gaps between v0.5.1 as-shipped and the Memory Discipline spec's intent
**Operator directive:** "C; plus additional build. No push yet. Seriously; get it right." (2026-08-21)
**Owner:** Release pipeline author
**Authored:** 2026-08-21

## 1. Purpose

Close the gaps between v0.5.1's wired state and the Memory Discipline spec's actual intent. The wiring pipeline made the primitives production-live; this pipeline addresses the substantive spec-fidelity gaps that remain — and, where a mechanism genuinely isn't shipping, deletes the false claim rather than lying about it.

Two categories:
- **Real fixes** — items where the code doesn't do what the spec says
- **Honesty pass** — items where the claim in docs/CHANGELOG doesn't match what the code does (DSPy compilation-recompilation, LeWM 23-dim drift). Remove the claim OR implement. This pipeline removes the claims and adds v0.6 backlog entries.

## 2. Non-goals

- No new architectural primitives (all needed pieces exist).
- No Kairos reference anywhere (hard-wall preserved).
- No DSPy compilation-recompilation implementation (deferred to v0.6; claim REMOVED from docs).
- No LeWM 23-dim drift detection implementation (deferred to v0.6; claim REMOVED from docs).
- No verify/review/commit/document functions (ADR-0036/0037 deferral stands; audit acknowledges).
- No 5 additional language chunkers (deferred to v0.6; grep-gate added refusing production use on unsupported extensions).

## 3. Sacred spine — invariants preserved

- Rootknot 3-signature schema unchanged (module_02 v4 factory now production-called).
- Author-name-free tree.
- Closed-IP wordlist zero-tolerance (post-filter-repo state; zero kairos anywhere).
- AL-1 property (structural per wiring module_07).
- Handshake-always for push (this pipeline does NOT push).

## 4. Module map

Each module: chain (PRE, Depth + Lateral) → build → chain (POST-pre) → audit (SP, external reviewer with source inline, ≥5 questions at 8000 tokens) → chain (POST-post) → BUILD what emerged → close. **Every SP prompt MUST ASK: "Does this actually close the spec gap it claims to close? Show the spec citation + the code + the test that proves the fidelity."** New commit per module (revert-friendly).

### module_01 — Docs honesty pass

Addresses **audit items 4, 5, and the release-label honesty question**.

- CHANGELOG `[0.5.1]` section rewritten to accurately describe what ships:
  - Add explicit "Substrate shipped; not yet spec-complete" framing.
  - List `verify/review/commit/document` verbs as v0.6 deferral (ADR-0036/0037 cross-ref).
  - List cross-function grouping as v0.6.
  - List 5 language chunkers (Java/Kotlin/C#/C/C++) as v0.6.
  - List `refuse_if_over_max` + 15% state-cap + SUMMARY-chunk + nightly-failure-job + subagent-cascade + index_digest + verifier-availability + write-first-invariant as ADDRESSED IN THIS PIPELINE.
- **Remove false claims from all docs:**
  - `docs/ROADMAP.md` — any DSPy signature-compilation reference reframed as v0.6+ intent (not shipped).
  - `docs/ROADMAP.md` — any LeWM drift-detection reference reframed as v0.6+ intent.
  - `CHANGELOG.md` — no mention of DSPy or LeWM in `[0.5.1]` section (moved to `[Unreleased]` or v0.6 backlog).
  - `docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md` — add "Not-yet-shipped" callout for §Self-Adjustment mechanisms 3 (DSPy) and 4 (LeWM).
- Update `docs/THREAT_MODEL.md` if it references either mechanism.
- Update `docs/EVENTS.md` — remove any event kinds that were declared but unemitted.
- **ADR-0043**: "DSPy compilation-recompilation deferred to v0.6" — documents rationale (not in pyproject.toml, no compilation/ dir, spec claim removed).
- **ADR-0044**: "LeWM 23-dim drift detection deferred to v0.6" — same shape.

**Regression:** `tests/test_release_surface.py` — add gate refusing `dspy` and `lewm` string mentions in `[0.5.1]` CHANGELOG section (allowlist: ROADMAP v0.6 backlog + this-pipeline module fragments in `_BUILD/` which are gitignored anyway).

### module_02 — Budget hardening: `refuse_if_over_max` + 15% state_context sub-budget

Addresses **audit items 1, 2** (Lens 1A CRITICAL).

- **Wire `refuse_if_over_max`:** grep every invocation harness call site; add pre-invocation call to `refuse_if_over_max(...)` alongside the existing `refuse_over_ceiling`. On refusal, raise structured `BudgetInputMaxExceeded` error that composition can catch + retry with narrowed context.
- **15% state_context sub-budget cap:** in the assembly path where `state_context` section is seated, enforce `len(state_bytes) <= floor(0.15 * input_target)`. If over, compress via same mechanism as `retrieved_bundle` cascade OR drop lowest-priority state entries. Add `state.budget_capped` trace event on drop.
- Both changes accompanied by:
  - Unit test proving `input_max` is hard-refused (was: silently accepted between max and hard_ceiling)
  - Unit test proving state_context ≤ 15% of input_target (was: unbounded)
  - Integration test proving pipeline still executes end-to-end with the new gates

### module_03 — Write-first-invariant hardening + `trace/writer.py` repair module

Addresses **audit Lens 2 Delta 1** (v0.2 primitive §5.1.2, §5.1.3 salvageable content).

- **Write-first-invariant strengthening** in `JsonlEventWriter`:
  - Every `append()` returns only after fsync + rename-atomic completes; no observer sees the event before durable write.
  - Add `WriteFirstViolation` exception raised if any observer is invoked pre-durability.
- **Repair module:** `src/ract/trace/repair.py`:
  - `repair(events: Iterable[Event]) -> RepairedEventStream` — deterministic + idempotent.
  - Handles: truncated last event, unclosed turn boundaries, tool call w/o result, LLM request w/o response, loop entered w/o exit, fiber activated w/o disposed.
  - Synthesizes close events for open handles at time-of-repair.
- **Regression:** `tests/unit/test_write_first_invariant.py` — construct scenario where observer would fire pre-fsync; assert `WriteFirstViolation` raised. `tests/unit/test_trace_repair_deterministic.py` — repair twice same log; assert identical output.

### module_04 — Cross-function grouping rules

Addresses **audit Lens 1C HIGH C-1**.

- New file: `src/ract/memory/grouping.py`
- API: `group_symbols(symbols: list[Symbol], rules: GroupingRules) -> list[SymbolGroup]`
- Rules per spec §Cross-Function Grouping:
  - Python dataclass + all its methods
  - Rust trait + implementing impl blocks (retrieve when query is about the trait)
  - Test function retrieves with subject function (heuristic: `test_foo` retrieves with `foo`; `class TestFoo` retrieves with `class Foo`)
  - Function retrieves with its type aliases (module-scope `X = Y | Z` type aliases used in signatures)
- Wire into `retrieve.py` at bundle-assembly time: `symbols = group_symbols(symbols, ctx.grouping_rules)`.
- Configurable per project via `.ract/grouping_rules.yaml` (optional; defaults ship).
- **Regression:** `tests/unit/test_grouping_dataclass.py`, `test_grouping_trait_impl.py`, `test_grouping_test_subject.py`, `test_grouping_type_aliases.py`.

### module_05 — SUMMARY chunking + Bonsai council fallback + oversize handshake

Addresses **audit Lens 1C MEDIUM** (`format_chunk(SUMMARY, ...)` returns "summary unavailable" + oversize handshake improvements).

- Wire actual SUMMARY generation:
  - Primary: use local Bonsai council model (from spec — `bge-small`-adjacent scale). NOTE: verify a Bonsai council model is actually available in RACT; if NOT, defer to a fallback like OpenRouter with explicit config gate — DO NOT invent a dependency.
  - Fallback: extract signature + first-line docstring + control-flow summary from AST (no model call — deterministic).
- Update `chunker.py` sub-chunking: replace blank-line heuristic with per-language AST boundary walker (for/while/if/else/try/except regions per spec §Chunk Overflow).
- **Regression:** oversize function → sub-chunks with correct AST boundaries; SUMMARY format returns non-"summary unavailable" content.

### module_06 — CANCELLED per Ox Alpha adversarial review 2026-08-21

**Original scope** (deferred): Failure-learning nightly job + human-review queue + retrieval-strategy adjustment surface (audit Lens 1F MEDIUM).

**Cancellation rationale** (Ox Alpha critique verbatim, `_BUILD/ract_v0.5.1_spec_completeness/ox_alpha_reviews/pipeline_challenge_2026-08-21.md` §1): *"A human-review queue with no operator workflow is dead code on arrival. An 'adjustment surface' with no retrieval-path reader is the primitive-without-wiring trap, pre-committed. ADR it to v0.6 exactly like ADR-0043/0044. This also shrinks your highest-risk module out of existence before it can hurt you."*

**Deferral:** ADR-0045 — "Failure-learning nightly job + human-review queue + retrieval-strategy adjustment deferred to v0.6" (authored in module_08's docs pass; formalizes the deferral analogously to ADR-0043 DSPy + ADR-0044 LeWM).

**Impact:** pipeline shortens from 8 to 7 modules. module_07 + module_08 keep their numbers (renumbering would corrupt ledger provenance). module_08's re-audit hardened per Ox Alpha §3 (4 sneak-vector defenses).

### module_07 — Lens 2 remaining deltas: verifier availability pre-check + SubagentHandle cascade + index_digest equivalence

Addresses **audit Lens 2 Deltas 2, 3, 4**. **Hardened per Ox Alpha adversarial review 2026-08-21 §2**.

- **Verifier availability pre-check:** `predicate.available(snapshot: WorkspaceSnapshot) -> bool`. Called during `build_loop_state` — if any predicate's verifier is unavailable (tool missing, config missing), loop refuses to enter with clear error naming the missing verifier.
- **SubagentHandle wired to compensator stack:** register handle with compensator stack; on parent loop halt (non-T1), cascade dispose. **Ox Alpha requirement:** integration test that **FORCES a subagent failure end-to-end** and asserts cascade fires — not unit tests of the cascade in isolation. A cascade with only isolated unit tests is unwired-in-anger.
- **`index_digest()` on 3 indexes:** each of symbol/graph/semantic exposes `.digest()` returning hash of internal state. **Ox Alpha requirement:** module plan MUST name the exact production caller that short-circuits reload on unchanged digest, BEFORE build starts. If no named caller exists, this sub-item is CANCELLED (utility functions with green tests + zero production callers are the classic residue of wiring pipelines).
- **Regression:** each fix has an integration test; cascade test forces failure; digest test asserts named-caller consumption.

### module_08 — Release close + re-verify audit + ADR-0045 + re-tag v0.5.1 (third)

- Full pytest suite green.
- Golden hash re-locked.
- ADR-0045 authored (module_06 cancellation → v0.6 deferral, per Ox Alpha §1).
- **Re-run source-spec audit** at `_BUILD/audit_2026-08-21d/` — verify items 1, 2, 3, 6-fix-or-defer, 8, 10 CLOSED; items 4, 5, 7, 9 explicitly DEFERRED via ADR (nightly failure job now item 9, deferred via ADR-0045).

**Ox Alpha §3 hardening of re-audit (MANDATORY — 4 sneak-vector defenses):**
- **Scope-narrowing via ADR:** re-audit reports TWO numbers per lens — (a) open against original spec, (b) open against ADR-amended spec. Delta is the honesty metric. Every ADR-deferred item appears in final report as a counted line with owner + version target (deferred is a STATUS, not a closure).
- **Auditor capture via excerpt selection:** SP prompts do NOT allow the primary to hand-pick spec excerpts. Give SP the full section list with SHA hashes; SP picks OR pre-commit a random seed for sampling. Documented in module_08 SP prompt template.
- **Test-oracle circularity:** one cold-read exercise — an agent that has NOT seen the code reads the spec and states what it believes v0.5.1 does; diff against reality. Divergence surfaces reading-error tests bake in.
- **Severity laundering:** every "by-design" reclassification requires SP approval, not builder assertion. Grep for reclassifications in module fragments; each must have SP citation.

**Ox Alpha CHANGELOG-presence retroactive gate:** grep `[0.5.1]` for named appearance of each shipped module (02 budget hardening, 03 write-first + repair, 04 grouping, 05 SUMMARY chunk, 07 verifier availability + cascade + digest). Missing → block re-tag until CHANGELOG updated.

- Version stays `0.5.1`.
- CHANGELOG `[0.5.1]` reflects final state (from module_01 rewrite + this pipeline's additions + ADR-0045 deferral).
- Backup old tag: `git tag backup-v0.5.1-preSpecCompleteness v0.5.1`.
- Re-tag `v0.5.1` at module_08 close commit.
- HANDSHAKE_PUSH_COMMANDS.md written with explicit gating language ("HANDSHAKE REQUIRED. Operator must explicitly execute...").
- **NO PUSH.**

## 5. Gate matrix additions

| Gate | Enforcer | Module |
|---|---|---|
| CHANGELOG `[0.5.1]` contains no false DSPy/LeWM claim | grep-gate test | 01 |
| ADR-0043 + ADR-0044 exist | test_release_surface.py | 01 |
| `input_max` hard-refuses | `test_budget_input_max_hard_refuse.py` | 02 |
| state_context ≤ 15% enforced | `test_state_context_15pct_cap.py` | 02 |
| Write-first-invariant hardening | `test_write_first_invariant.py` | 03 |
| Trace repair deterministic + idempotent | `test_trace_repair_deterministic.py` | 03 |
| Cross-function grouping fires | 4 unit tests | 04 |
| SUMMARY format returns real content | integration test | 05 |
| Sub-chunking uses AST boundaries | property test | 05 |
| Nightly job proposes + queue populated | integration test | 06 |
| Verifier availability pre-check refuses loop entry | integration test | 07 |
| SubagentHandle cascades on parent halt | integration test | 07 |
| index_digest short-circuits reload | integration test | 07 |
| 8-lens audit re-verify | ad-hoc | 08 |
| **Ox Alpha CHANGELOG-presence gate:** every shipped module appears in `[0.5.1]` with behavior change described | test_release_surface.py grep-gate (retroactive on 02/03/04/05/07; forward on 08 close) | 08 |
| **Ox Alpha module_08 §3 4-vector re-audit hardening** | module_08 audit prompt template + report shape | 08 |
| **Ox Alpha named-caller requirement** for module_07 index_digest sub-item | in-plan review before build | 07 |
| **Ox Alpha forced-failure integration test** for module_07 SubagentHandle cascade | tests/integration/test_subagent_cascade_forced_failure.py | 07 |

## 6. Second-Pass discipline update

Every SP prompt this pipeline MUST include:
- Q: "Does this actually close the spec gap it claims to close? Cite spec § + code line + regression test."
- Q: "What test asserts the fix (not just that new code exists)?"
- Q: "Any hidden false claims left in the CHANGELOG or docs after this module?"

## 7. Rollback protocol

Each module lands as one commit. `git revert <sha>` in reverse order.

## 8. Handshake

Push happens ONLY after operator confirmation in chat. This pipeline writes HANDSHAKE_PUSH_COMMANDS.md at module_08 close; operator gates.
