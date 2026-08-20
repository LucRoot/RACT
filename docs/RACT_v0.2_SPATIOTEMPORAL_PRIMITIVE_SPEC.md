# RACT v0.2 Spatiotemporal Composability Primitive — Implementation Spec

**Ships as:** version TBD by operator (spec target: an architectural substrate that supersedes current RACT-native lifecycle plumbing; likely ships as v0.6.0 or v1.0.0 given the scope; the source doc labels itself "v0.2" as its own internal scoping)
**Source doc:** `C:/Users/rootl/Downloads/04-RACT-DESIGN.md` (970 lines, authored by operator)
**Companion docs referenced by source:** `01-FORMAL-CORE.md`, `02-CODE-TRACE.md`, `03-[REDACTED]-DESIGN.md` ([REDACTED] primitive spec)
**Owner:** [REDACTED] Builder
**Authored:** 2026-08-20

## 1. Purpose

Introduce the Spatiotemporal Composability Primitive (session log, fiber lifecycle, coeffect declarations, transactional file operations, subagent orchestration, three-index memory as coeffects) as RACT's runtime substrate. Convention becomes structure. Environment-centered authority, acceptance predicates, and transactional execution become STRUCTURALLY enforced rather than convention-enforced.

## 2. Non-goals (from source doc §3, restated)

- Not a replacement for environment-centered authority discipline (substrate, not verifier).
- Not a substitute for git (in-loop revertibility; git remains durable-transactionality).
- Not an event-sourcing framework (state lives in memory during session; log is post-hoc + repair).
- Not a UI framework (TUI subscribes to fiber events; primitive publishes).
- Not multi-user or multi-repo orchestration (deferred).

## 3. Sacred spine — invariants preserved through migration

- Rootknot 3-signature schema unchanged. Rootknot creation now happens INSIDE a fiber's provider service; canonical bytes unchanged.
- Author-name-free tree.
- Closed-IP wordlist zero-tolerance.
- AL-1 property preserved by acceptance-predicate coeffect enforcement (loops STRUCTURALLY cannot activate without predicates satisfied).
- Handshake-always for push.
- **Backward compatibility:** v0.5.x session artifacts + Rootknots readable during the transition. `format_version` field distinguishes eras.

## 4. Dependencies

- **[REDACTED] primitive:** RACT depends on [REDACTED] as inference source. Doc says "RACT and [REDACTED] share the same runtime kernel." Verify [REDACTED] primitive is available at Pipeline B execution start; block Pipeline B modules R2+ if not.
- **Cordis-shape reference:** doc references `packages/core/session/` from a Cordis TypeScript codebase. Not a code dependency — a design reference. Extract the shape (append-only log with typed events, replay, repair, scope-filtered dispatch) into pure-Python `ract.session` module.

## 5. Module map (matches source doc §4 R1-R7 adoption phases + wraps)

### module_00 — Spec-derivation + [REDACTED]-availability guard
Verify [REDACTED] primitive is available (import path + minimal-plugin roundtrip). If absent, block pipeline with clear error naming what's needed. Write `[REDACTED]_INTERFACE.md` capturing the exact surface RACT will import from [REDACTED] (subset of the primitive: `Context`, `plugin`, `inject`, `effect`, `provide`, fiber lifecycle events, `equivalence` type).

### module_01 — Phase R1: Session log (`ract.session` module)
Deliver the append-only session log per source doc §5.1.1-§5.1.5:
- `SessionEventType` enum (turn boundaries, LLM, tool, loop, fiber, predicate, file, subagent, session)
- `SessionLog` class with write-first invariant, two observer classes (post-commit + durability)
- `SessionRepair` class with deterministic idempotent repair
- `ScopedSessionLog` with parent-scope containment
- `snapshot_json_value()` canonical serializer (JCS-shaped; NaN/Inf/cyclic-ref rejects, non-string keys reject, sorted deterministic output). NOTE: aligns with v0.5.1 module_03 canonical JSON — Pipeline B module_01 depends on v0.5.1 module_03 landing first (if v0.5.1 not yet released, inline the JCS helper here and reconcile in later cleanup).
- Every existing RACT event captured as SessionEvent (user turns, tool calls, LLM calls, loop transitions) as pure-add; no existing behavior changes.
- Regression: log capture → replay → repair fidelity; scope filtering; snapshot serialization property tests.

### module_02 — Phase R2: One RGoL loop as a fiber
Pick simplest existing RGoL loop (recommend "read a file, summarize, respond"). Refactor as plugin with `@inject(['file_reader', 'llm'])`. Verify full lifecycle observable from session log alone. Success criterion: log-derived state matches in-memory state at every transition.

### module_03 — Phase R3: Transactional file operations (`ract.io.transactional`)
Deliver `TransactionalFile` + `apply_edit_reversibly` per source doc §5.4. Migrate all file writes in RACT to route through it. LIFO revert ordering for multi-write loops. Git boundary: successful loop's writes promote to git via `git add + commit`; disposer becomes `git reset --soft` compensator. Regression: partial-failure filesystem-residue test suite; boundary-crossing property tests.

### module_04 — Phase R4: Acceptance predicates as coeffects
Migrate acceptance predicate discipline to coeffect declarations per source doc §5.3. Verifier plugins provide `predicate:tests_pass`, `predicate:no_lint_errors`, `predicate:<user-defined>`. Loops `@inject(['predicate:...'])`. Cannot activate without satisfiability; cannot provide success service if any predicate check fails. `predicate_equivalence` implements `≃` comparison over signature+context. Regression: predicate-cascade tests (violation deactivates dependents in dependency order).

### module_05 — Phase R5: Remaining RGoL loops
Mostly mechanical once R2 + R4 proven. Migrate all remaining RGoL loops to plugin shape. `to_plugin(v01_component)` adapter (source doc §9.3) for legacy-shape loops during transition. Migrate in dependency order (leaves first, roots last).

### module_06 — Phase R6: Subagent orchestration
Subagents become plugins spawned by parent contexts per source doc §5.6. `spawn_research_subagent(ctx, task) → Fiber`. Parent-child fiber relationships give cascade: dispose parent → every subagent unwinds via disposer accumulator. Session-log scope: subagent events scoped to subagent fiber. UI panel subscribes at scope; parent view subscribes broader. `ctx.isolate('workspace')` opt-in isolation.

### module_07 — Phase R7: Three-index memory as coeffects
Semantic + temporal + lexical indices become provider fibers with equivalence relations per source doc §5.7. Each subscribes as durability observer to session log. Index rebuilds do not cascade to consumers when behaviorally equivalent. Post-hoc reconstruction: replay log to seq N → freshly-instantiated indices → query → matches historical state.

### module_08 — [REDACTED] interaction closure
Per source doc §6. Wire `@inject(['[REDACTED]:model_adapter'])` for RACT's LLM service. Cascade on [REDACTED] adapter withdrawal: RACT `llm` service → PENDING → RACT loops → PENDING → [REDACTED] reload → cascade reversal. [REDACTED]-side events matter for RACT: subscribe to [REDACTED] fiber lifecycle → re-emit as `[REDACTED]_ADAPTER_RELOADED` into RACT log.

### module_09 — Property tests + integration tests + corruption tests
Per source doc §8:
- Property 1 (log-to-state fidelity): hypothesis-based over any session
- Property 2 (transactional atomicity): filesystem post-failure identical to pre-loop for any N writes ≤ K
- Integration: log-derived reconstruction matches ground truth; process-kill mid-loop restart-recovery; cascade under [REDACTED] reload; confluence under concurrent verifier rebuilds
- Corruption tests: truncated at random offsets, malformed events, duplicate sequences, out-of-order — repair produces sane session or fails loudly, never silently-wrong

### module_10 — Backward-compat + migration guide + close
- `format_version` header on session logs; v0.5.x logs auto-repair-migrate to v0.2 events on first load per source doc §9.2
- `to_plugin()` adapters documented + covered by tests
- Migration guide for community contributors (source doc §9.4)
- Deprecation notices for v0.5.x lifecycle methods, direct file writes, ad-hoc acceptance predicate checks
- Version bump + CHANGELOG + tag + HANDSHAKE_PUSH_COMMANDS.md; operator handshake gates push.

## 6. Gate matrix

| Gate | When |
|---|---|
| [REDACTED] primitive reachable | module_00 |
| Session log write-first invariant | module_01 |
| Repair idempotent | module_01 |
| Loop-lifecycle fully observable from log alone | module_02 |
| Transactional atomicity (K=8) | module_03 |
| Predicate cascade correct in dependency order | module_04 |
| All legacy loops migrated | module_05 |
| Subagent cascade correct on parent disposal | module_06 |
| Three-index equivalence | module_07 |
| [REDACTED] cascade reversal | module_08 |
| Log-to-state fidelity property | module_09 |
| Corruption tests | module_09 |
| Backward-compat with v0.5.x logs | module_10 |
| Golden hash locked | module_10 |
| Closed-IP wordlist 0 | Every module |
| AL-1 property | Every module |

## 7. Open questions (from source doc §10; requires operator sign-off before module_01 start)

- Q1: session log per-session or per-workspace? Recommend per-workspace with logical session boundaries.
- Q2: log storage format? Recommend NDJSON for append; SQLite derived index rebuilt on load if NDJSON > threshold.
- Q3: fiber lifecycle publishing level? Recommend all events at DEBUG; user-visible at INFO.
- Q4: retention policy? Recommend NO auto-retention in v0.2 — `session log prune` command; automatic in v0.3.
- Q5: subagent isolation default? Recommend shared context default; `ctx.isolate('workspace')` opt-in.
- Q6: verifier composition? Recommend renaming per-language (`predicate:tests_pass:python`) — realms deferred to v0.3.
- Q7: irreversible tool compensation? Recommend `irreversible` flag; loops commit preceding effects at that call boundary.
- Q8: TUI as post-commit or durability observer? Recommend post-commit + tail-reconcile on restart.
- Q9: Substack/Medium publishing integration? Recommend flagging as v0.3+.

**Operator sign-off required on Q1-Q9 before module_01 execution begins. Present recommendations + accept operator overrides.**

## 8. Rollback protocol

Modules build on each other (R1 needed for R2; R3 independent). Rollback:
- module_10 revert = leave v0.2 code in tree but revert version bump; no user-visible ship
- module_02+ revert = leave R1 log in tree; RGoL loops remain in legacy shape
- module_01 revert = full pipeline unwound; back to v0.5.x baseline

## 9. Handshake

Push happens after Pipeline A' (v0.5.1) AND Pipeline B (this one) both land. Operator confirms in chat.
