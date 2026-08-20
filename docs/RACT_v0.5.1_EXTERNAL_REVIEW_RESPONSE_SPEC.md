# RACT v0.5.1 External Review Response Spec

**Ships as:** v0.5.1 (patch bump; response to external reviewer chain)
**Owner:** Release pipeline author
**Authored:** 2026-08-20
**Inputs:** `_BUILD/ract_v0.5.1_external_review/` — DeepSeek rounds 1-5 + REVIEW_4_UNKNOWN_REVIEWER (1086 lines total, triangulated)
**Governing consolidator:** `DEEPSEEK_REVIEW_5.md` (concrete implementation designs for G1/G2/G3 compaction-continuity gaps)

## 1. Purpose

Close the 200-compaction trust chain broken by three triple-triangulated blockers (G1 AssumptionRegistry crash-loss, G2 workspace-snapshot-not-in-signed-payload, G3 prompt-drift-invisible), plus fold nine secondary blockers surfaced across five reviewer rounds. Ships as v0.5.1 patch — no breaking changes to Rootknot 3-signature schema; SCHEMA_VERSION bumped only for canonical-bytes extensions with backward-read for v0.5.0 payloads.

## 2. Non-goals

- No refactor to v0.2 Spatiotemporal Primitive substrate (separate pipeline; queued).
- No new external inference sources.
- No breaking Rootknot signature schema. Extend canonical bytes with new required fields; preserve v0.5.0 read-path via SCHEMA_VERSION dispatch.
- No golden-hash bump beyond what the source changes demand (source-digest test rewrites hash post-close).

## 3. Sacred spine — invariants preserved

- Rootknot 3-signature schema (generator / environment / anti-lazy) preserved. New fields added inside `canonical_bytes`; signatures re-attest over extended payload.
- Author-name-free tree.
- Closed-IP wordlist zero-tolerance.
- AL-1 property.
- Handshake-always for push.

## 4. Module map

Each module: chain (PRE) → build → chain (POST-pre-audit) → audit (SP) → chain (POST-post-audit) → BUILD what emerged → close. Modules land as separate commits (revert-friendly).

### module_01 — RootknotWAL crash-consistency layer
Address G1 (triple-triangulated: R2 + R4 + R5). Introduce `.ract/assumptions.wal` (JSONL, one transition per line). Every `propose`/`accept`/`discharge`/`violate` appends before in-memory update. `fsync` per transition (assumption transitions are rare vs regular I/O). Load path: read `.ract/assumptions.json` snapshot + replay WAL tail; write path: append WAL, mutate memory, periodic snapshot rotates WAL. File-lock on Windows (`msvcrt.locking`) + POSIX (`fcntl.flock`). Every WAL entry ALSO emits `assumption.<transition>` event to `evals/runs/<run_id>/events.jsonl`. Regression tests: process-kill at each transition state proves replay fidelity.

### module_02 — Rootknot canonical-bytes extension (`workspace_digest` + `prompt_digest` + `run_id`)
Address G2 + G3 + REVIEW_4_UNKNOWN A2 (intent-in-signed-payload). Extend `canonical_bytes` schema with three new fields:
- `workspace_digest`: SHA-256 over `WorkspaceSnapshot.files` (sorted JCS bytes) + `timestamp` + `metadata` hash. Simpler first cut: git-commit hash of hidden snapshot commit; ancestor-check via `git merge-base --is-ancestor`.
- `prompt_digest`: SHA-256 of the intent text bytes at compile time.
- `run_id`: propagated through every artifact (fixes REVIEW_2 criticism 1 fragmented run_id).

SCHEMA_VERSION bumps `1 → 2`. v0.5.0 read-path preserved (SCHEMA_VERSION 1 payloads verify without new fields; new writes always at SCHEMA_VERSION 2). Regression tests: cross-version verify, hidden snapshot commit tree, ancestor check.

### module_03 — Canonical JSON serialization (RFC 8785 JCS)
Address REVIEW_4_UNKNOWN D2 (canonical JSON). Introduce `ract.canonical.dumps_jcs()` implementing JCS: sorted keys, no whitespace, UTF-8 NFC, closed float representation (`{-0.0 → 0.0}`, `NaN/Inf → error`), lossless integers. All canonical-bytes computations route through it. Existing custom sort-key serializer deprecated; grep-gate against direct `json.dumps(..., sort_keys=True)` in canonical paths. Regression: JCS test vectors from spec appendix; round-trip fidelity across Windows CRLF/LF.

### module_04 — Prompt-hash in AcceptanceSuite + T8 PROMPT_DRIFT termination
Address G3 (module_02 laid canonical-bytes field; this module wires the runtime enforcement). `IntentCompiler.compile` writes `prompt_digest` into `AcceptanceSuite`. Loop controller at each iteration recomputes `hash(intent)` and compares to `state.suite.prompt_digest`. Mismatch → force rollback to last known-good snapshot + halt with `TerminationCause.T8_PROMPT_DRIFT` (schema extension; ADR entry). Legitimate intent evolution path: `ract intent recompile <run_id>` operator-signed adds new suite version to chain (not replace). Regression: injection scenarios, operator-signed recompile, T1-T8 enum coverage.

### module_05 — SubstrateLoop shim-wiring closure (SUBSTRATE §4-§7 gap)
Address REVIEW_2 criticism 3 + REVIEW_3 arch drift. Current SubstrateLoop declares primitives but delegates most enforcement to caller-side conventions. Wire the shims: tool-invocation gate (§5), rollback SIGKILL to process group not just process (§7 hardening; addresses REVIEW_4_UNKNOWN B3), environ allowlist init (§4.3; addresses REVIEW_4_UNKNOWN D1 data-exfil), rollback compensator on git-commit boundary (§7). Regression: substrate-invariant property tests.

### module_06 — End-to-end run_id preservation smoke test
Address REVIEW_2 criticism 1 (fragmented run_id) via test that catches drift. New test `tests/integration/test_run_id_preservation.py` spawns a full loop, injects a compaction event mid-loop, asserts every artifact + Rootknot + WAL entry + event log line carries the same `run_id`. Fixes any surfaced drift as part of module_06 (may cascade to touch modules already landed).

### module_07 — Historical Manifest Ledger (RK-3 durability)
Address REVIEW_3 C1 (manifest is signed but ephemeral). Introduce `.ract/manifest_ledger.jsonl` — append-only ledger of every manifest_digest observed with its provenance (Rootknot signature, timestamp, tool trace). Enables historical audit + Merkle proof of "this manifest was seen at this time." Cross-links to RootknotWAL entries.

### module_08 — Polyglot G5/G6 via tree-sitter
Address REVIEW_3 C3 (G5/G6 currently Python-only via AST). Introduce `ract.parsers.tree_sitter_backend` supporting Python + JavaScript + TypeScript + Rust + Go as MVP. G5 (dead code) + G6 (test-copy paste) become language-dispatched. Optional dependency; graceful degradation with WARN when tree-sitter unavailable for a file's language.

### module_09 — Sycophancy classifier upgrade (AST-delta + WhispererContract-event)
Address REVIEW_4_UNKNOWN E1 (current sycophancy detector is regex-only, brittle). Replace with two-signal detector: (1) AST-diff between operator-request and model-response detects null-op agreement; (2) new event `whisperer.contract_violation` emitted when response's structural commitment count is below configured floor. Regression: known-sycophantic-response corpus + known-genuine-agreement corpus, F1 target ≥ 0.85.

### module_10 — Version bump + CHANGELOG + close + handshake
`VERSION` + `pyproject.toml` + `src/ract/__init__.py` → `0.5.1`. CHANGELOG `[0.5.1]` section itemizes each module with commit SHAs. Golden hash re-locked via `test_source_digest.py` failure → assert new hash. Full pytest suite green. Annotated tag `v0.5.1` (body ≤ 500 chars). HANDSHAKE_PUSH_COMMANDS.md written; operator handshake gates push. No push executed by pipeline.

## 5. Gate matrix (each module must satisfy)

| Gate | Enforcer | When |
|---|---|---|
| Rootknot signatures verify | `test_rootknot_signature_property` | Every module touching signed-payload |
| Canonical bytes reproducible | `test_canonical_bytes_deterministic` | Modules 02, 03, 04 |
| SCHEMA_VERSION dispatch | `test_schema_version_backread` | Module 02 |
| WAL crash-replay | `test_rootknot_wal_process_kill` | Module 01 |
| T8 fires on injection | `test_prompt_drift_termination` | Module 04 |
| Substrate invariants | `test_substrate_property` | Module 05 |
| Run_id preservation | `test_run_id_preservation` | Module 06 |
| Manifest ledger append-only | `test_manifest_ledger_immutable` | Module 07 |
| Polyglot G5/G6 coverage | `test_g5_g6_polyglot` | Module 08 |
| Sycophancy F1 ≥ 0.85 | `test_sycophancy_classifier` | Module 09 |
| Golden hash locked | `test_source_digest.py` | Module 10 |
| Closed-IP wordlist 0 | `test_no_closed_ip_terms_in_tracked_files` | Every module |
| AL-1 property | `test_antilazy_al1` | Every module |

## 6. Non-blockers deferred to v0.6+

- F2 semantic drift detector (defense in depth for G3; layered per REVIEW_4 verification).
- Realm-based verifier composition (v0.2 primitive Q6).
- v0.2 primitive substrate migration (Pipeline B).

## 7. Rollback protocol

Every module lands as one commit. Rollback = `git revert <commit>` in reverse module order. Golden hash test guards accidental partial rollback (SHA mismatch fails CI).

## 8. Handshake

Push happens only after both this pipeline AND Pipeline B (v0.2 primitive) land. Operator confirms in chat.
