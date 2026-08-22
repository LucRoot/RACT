:warning: This file is project documentation, not part of the source code.

# Changelog

All notable changes to RACT (Root Agentic Coding Tool) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.1] - 2026-08-21 — External Review Response (fully wired)

> **Wiring status.** Tag re-issued 2026-08-21 at the wiring-completion
> pipeline HEAD. The 2026-08-21 8-lens audit
> (`_BUILD/audit_2026-08-21/AUDIT_SUMMARY.md`) found that several
> primitives shipped clean-tested API surfaces with zero production
> callers. The v0.5.1 wiring-completion pipeline
> (`docs/RACT_v0.5.1_WIRING_COMPLETION_SPEC.md`, modules 01-11) closes
> every CRITICAL and HIGH finding via ten wiring commits (`c78d8b1` ..
> `53280ff`) plus this release-close commit. Re-audit at module_11
> (`_BUILD/audit_2026-08-21b/AUDIT_SUMMARY_v2.md`) verifies each
> primitive now has at least one production call chain from a runtime
> entry point. The prior tag `bb8e013` is preserved as
> `backup-v0.5.1-preWiring` and superseded. See the **Wired** section
> below for the per-module wire-in map.

Patch release for the External Review Response pipeline
(`_BUILD/ract_v0.5.1_external_review_response/`). This release closes
the trust-chain gap opened at the 200-compaction boundary that DeepSeek
rounds 1-5 + REVIEW_4_UNKNOWN_REVIEWER surfaced against v0.5.0: the
Rootknot signed surface is extended (not broken) with workspace, prompt,
and run-id digests; the assumption ledger crash-consistent; every hashed
byte-string travels through RFC 8785 JCS; a new PROMPT_DRIFT termination
cause plus operator-signed intent-recompile CLI verb close the intent-
mutation loophole; the SubstrateLoop shim closes its four SUBSTRATE
§4-§7 gaps (tool-invocation gate, process-group tree-kill, environ
allowlist, git-commit compensator); an ambient run_id ContextVar
preserves identity end-to-end across compaction; a historical Manifest
Ledger with Merkle chain adds tamper-detectable durability to RK-3;
G5/G6 laziness enforcement expands from Python-only to five polyglot
languages via tree-sitter; the sycophancy classifier gains an AST-delta
signal + WhispererContract event scoring F1=1.000 on a 48-sample
regression corpus. Tag is `v0.5.1`. Three ADRs added (ADR-0040 for
T8 PROMPT_DRIFT, ADR-0041 for SubstrateLoop shim closure, and
ADR-0042 for the sycophancy v2 tuning band — six more surfaces
carry inline ADR-style module docstrings).

### Per-module surface

- **module_01 — RootknotWAL crash-consistency (G1).** New
  `src/ract/core/assumptions_wal.py` (~475 lines) with append-only
  JSONL write-ahead log at `.ract/assumptions.wal`, cross-platform
  exclusive file lock, fsync per append, truncated-tail tolerance
  with WARN, middle-corruption refusal, and `AssumptionRegistry` wire
  so accepted assumptions durably replay across restart. New
  `EventKind.assumption_accepted` in the closed vocabulary. Primary
  `cf829d5`; SP amendment `fcc23af` (WARN emission on truncated tail
  + rotation-atomicity docstring correction).

- **module_02 — Rootknot canonical-bytes extension (G2 + G3 +
  REVIEW_4_UNKNOWN A2).** Three new opt-in fields on the Rootknot
  dataclass — `workspace_digest`, `prompt_digest`, `run_id` — plus
  `make_rootknot_v4()` factory bumping `schema_version` 3→4. New
  `src/ract/core/workspace_digest.py` with pure-hash
  `workspace_digest()` + `compute_prompt_digest()` + `run_id_hex()` +
  `WorkspaceDigestChain` ancestor ledger. `AcceptanceSuite.prompt_digest`
  optional field populated by `IntentCompiler.compile()`. Sacred spine
  preserved — the three signed byte-strings extend, nothing removed.
  Primary `88c35a6`; SP amendment `8dbf452` (strict-JSON metadata_hash
  + `MetadataUnserialisableError`, exclusive-lock on chain read path,
  `require_prompt_digest()` helper).

- **module_03 — RFC 8785 JCS canonical JSON.** New `src/ract/canonical.py`
  (462 lines) with `dumps_jcs`/`loads_jcs`/`is_canonical`/
  `CanonicalJSONError` implementing strict-JSON NFC-normalised codepoint-
  sorted ECMA-262-conformant serialiser. 15-file migration of every
  hash-input path: `rootknot.py`, `predicate.py`, `workspace_digest.py`,
  `assumptions_wal.py`, `plan.py`, `security/manifest.py`,
  `trace/events.py` + `writer.py`, `receipt.py`, `receipt_chain.py`,
  `run_fingerprint.py`, `reproducibility_manifest.py`,
  `mutation_merge_gate.py`, `antilazy/symgraph.py`, `memory/cache.py`,
  `memory/query_trace.py`, `memory/functions/contracts.py`,
  `memory/retrieve.py`. Grep-gate at
  `tests/architecture/test_no_sort_keys_in_canonical_paths.py` (tokenize-
  based comment/string blanking + stale-allowlist sanity + 20-entry
  allowlist). Primary `98931c4`; SP amendment `2205309`
  (`__json_snapshot__` cycle guard + explicit opt-out, shortest-repr
  number encoding replacing initial log10 + `.17f`, non-ASCII invariant
  tests, look-back window widened 8→50).

- **module_04 — T8 PROMPT_DRIFT + T9 PROMPT_DIGEST_MISSING + `intent
  recompile` CLI verb.** New termination causes T8 (mutation-detected)
  and T9 (opt-in strict-prompt-digest missing) added to the closed
  `TerminationCause` enum with pinned integer values. New
  `src/ract/core/suite_chain.py` (~340 lines) append-only JSONL ledger
  of AcceptanceSuite versions per run with cross-platform file lock,
  fsync per append, tail-truncation tolerance, and middle-corruption
  refusal. New `src/ract/core/intent_recompile.py` (~280 lines)
  operator-signed recompile action loading key from `.ract/operator.key`
  OR `RACT_OPERATOR_KEY` env var, HMAC-SHA256-signed recompile bytes,
  and initial-entry lazy record. `LoopController._check_prompt_drift`
  per-iteration hook with chain-head comparison, initial fallback, T8
  halt, and rollback to `last_known_good_workspace`. New ADR-0040. New
  `ract intent recompile <run_id>` CLI verb (mutually-exclusive
  `--intent-file` / `--intent-text`). Primary `1186f8d`; SP amendment
  `9d4acc6` (Q1 pinned enum values, Q2 orphan-file enumeration + opt-in
  `delete_orphaned_files_on_t8`, Q4a resolved key path, Q4b T9 +
  `strict_prompt_digest`, Q5a `.recompile_lock`, Q5b eager initial
  entry, Q6b split exit codes 2/3/4/5).

- **module_05 — SubstrateLoop shim-wiring closure (SUBSTRATE §4-§7 +
  B3 + D1).** Four new modules close the executor gap. New
  `src/ract/executor/tool_gate.py` (549 lines) with four-gate
  `ToolInvocationGate` + closed-type `ToolArgSchema` + frozen
  `ToolRegistry` + `ToolInvocationRefused` structured shape + bounded
  `args_repr` for privacy + `tool.invocation.pre|post|refused` events.
  New `src/ract/executor/process_group.py` (460 lines) with POSIX
  `setsid` via `start_new_session` + Windows `CREATE_NEW_PROCESS_GROUP`
  + Job Object with kill-on-close + `killpg`/`TerminateJobObject` reap
  + `taskkill /F /T` fallback + optional SIGTERM grace period. New
  `src/ract/security/sandbox_env.py` (370 lines) with `DEFAULT_ALLOWLIST`
  (44 POSIX+Windows+locale names) + `NEVER_PASSTHROUGH` (17 credential
  names) + `build_sandbox_env` with count-only WARN + JSONL loader that
  refuses malformed configs. New `src/ract/executor/commit_compensator.py`
  (346 lines) with `CommitCompensator` (soft-reset default) +
  `CompensatorStack` LIFO drain + `check_pushed` via
  `git branch -r --contains` + refusal-of-pushed-commits +
  install/discard/apply/refused events. ADR-0041 names four decisions
  + five rejected alternatives. Primary `ed62a47`; SP amendments
  `75eda12` (Q2 CREATE_SUSPENDED + `_resume_thread`, Q3a
  NEVER_PASSTHROUGH_PREFIXES + case-insensitive + glob refusal, Q3b
  `_redact_name_for_log`, Q3d utf-8-sig read + per-line BOM strip,
  Q4c `_resolve_branch` + `_current_branch` + `git update-ref`, Q5b
  HEAD-read post-fast-forward gates `parent_snapshot`, Q5c
  `dispose(success=False)` resyncs) + `12d933f` + `968fe64`.

- **module_06 — ambient run_id ContextVar + end-to-end preservation
  smoke.** New `src/ract/runtime.py` (140 lines) with ContextVar-
  backed `run_id` accessor + `bind_run_id` context manager +
  `set/reset` primitives + type/empty guards. WAL `_persist` stamps
  ambient into payload when caller omits `run_id`.
  `WorkspaceDigestChain.append` accepts explicit `run_id` kwarg +
  falls back to ambient + `ChainEdge.run_id` optional field for
  backward-compat. `JsonlEventWriter` and `make_rootknot_v4` accept
  `run_id=None` and decode ambient hex→bytes, refusing when no
  ambient bound (control-bypass guard). `LoopController.run()` binds
  ambient at entry via `_resolve_or_mint_run_id` (marker file →
  basename → mint fresh 32-hex + write marker for compaction
  survival). Primary `39789e2`; SP amendment `ab5ecdc` (Q1
  `run_with_ambient(fn,*args,**kwargs)` closure pattern, Q2 WAL WARN
  on explicit-vs-ambient divergence, Q4 cross-platform exclusive
  lock on `run_id.txt.lock` sidecar, Q5 WAL reload WARN on
  bound-ambient with legacy no-rid entries).

- **module_07 — Historical Manifest Ledger (RK-3 durability).** New
  `src/ract/security/manifest_ledger.py` (~1000 lines) with
  `ManifestLedger` append-only JSONL at `.ract/manifest_ledger.jsonl`
  + content-addressable snapshot store at
  `.ract/manifest_snapshots/{digest_hex}.json` (idempotent CAS via
  tmp+os.replace) + Merkle chain via `prev_ledger_hash` (GENESIS
  sentinel for first entry) + cross-platform file lock mirroring
  `assumptions_wal.py` (msvcrt.locking Windows + fcntl.flock POSIX,
  3-attempt/10ms backoff, LedgerLockContended) + `verify_chain`
  returning `LedgerVerifyResult{valid, first_break_at,
  tail_valid_count}` detecting middle-tamper AND surfacing truncated-
  tail via reduced count + `proof_of`/`verify_proof` with loader-based
  full-chain mode + idempotence by `(run_id, manifest_digest)` within
  run + ambient ledger accessor + WAL cross-link via
  `count_wal_entries`. New EventKind `manifest.ledger.appended` in
  closed vocabulary. `Rootknot.attest_environment` wired to call
  `record_environment_attestation` post-signing via local import
  breaking security→core cycle — signed RK-3 payload unchanged.
  Primary `2cb42b4`; SP amendment `dbd0a73` (Q1 `_entry_schema_valid`
  mandatory-field shape check, Q3 per-process/per-thread CAS tmp path
  `.json.tmp.{pid}.{tid}`, Q5 `manifest.ledger.refused` EventKind +
  WARN wrap in observer, Q6 `verify_proof` now REQUIRES loader +
  raises ValueError when None + new `verify_proof_shape_only` static
  method).

- **module_08 — Polyglot G5/G6 via tree-sitter.** New
  `src/ract/parsers/tree_sitter_backend.py` (~340 lines) with
  `Language` enum (PYTHON/JAVASCRIPT/TYPESCRIPT/TSX/RUST/GO) +
  `LANGUAGE_BY_EXTENSION` map covering 10 MVP extensions +
  `ParseTree`/`ParseError` dataclasses + cached `_load_grammar` per
  language + `parse(file_path, source_bytes)→ParseTree|None`
  byte-oriented hot path + `parse_file` convenience +
  `iter_nodes`/`node_text`/`field_named` walk helpers +
  `tree_sitter_available` probe. New
  `src/ract/antilazy/dead_code_polyglot.py` (~440 lines) with
  `DeadCodeCandidate`/`DeadCodePolyglotReport` +
  `scan_dead_code`/`scan_dead_code_in_dir` public APIs +
  Python-parity via stdlib `ast` (never routed through tree-sitter) +
  per-language dispatch for JS/TS/Rust/Go. New
  `src/ract/antilazy/test_copy_paste_polyglot.py` (~450 lines) with
  token-normalised Jaccard fingerprint (`jaccard_threshold=0.85`,
  `min_tokens=6`) + per-language test-body extractors (Python pytest
  `test_*`, JS/TS/TSX `call_expression it/test/describe/t`, Rust
  `#[test]` via `_collect_scope`, Go `func Test*` in `*_test.go`).
  `enforce_g5_dead_code_polyglot` + `enforce_g6_test_copy_paste_polyglot`
  wired in `pre_commit.py`; legacy `enforce_g5`/`enforce_g6` untouched
  (additive-only preservation). `pyproject.toml [polyglot]` optional-
  dep group. Primary `c74f717`; SP amendment `da24c63` (Q1 public
  `reset_grammar_caches()`, Q2 `visit_AnnAssign` for `x: SomeType = 1`,
  Q3 destructuring `object_pattern`/`array_pattern` in
  `_collect_declarator_decls`, Q4 `_extract_rust._collect_scope`
  resets `prev_attr_text`, Q5 `iter_nodes` `DEFAULT_MAX_STACK_DEPTH`
  = 10_000 + `max_stack_depth=None` opt-out, Q6 `_lang_group_key`
  folds typescript+tsx into one Jaccard group).

- **module_09 — Sycophancy classifier v2 (AST-delta + WhispererContract-
  event).** New `src/ract/antilazy/sycophancy_v2.py` (~640 lines) with
  two-signal classifier: Signal 1 AST-delta null-op score over fenced-
  block-extracted request/response with identifier-name intersection to
  distinguish verbatim-echo from new-structural, Signal 2
  `commitment_count = ast_new_commitments + factual_claims` (sentences
  carrying distinguishing predicates: numbers, backtick tokens,
  snake_case, camelCase, file paths, ~50 measurement/operational
  verbs), combined as `is_sycophantic = (null_op_score > 0.7) OR
  (commitment_count < 3)`. New EventKind
  `whisperer.contract_violation` in closed vocabulary emitted via
  best-effort emit on composed verdict. Legacy
  `ract.antilazy.sycophancy` reversal-scan preserved unchanged for its
  own trace-scanning use case. New `tests/fixtures/sycophancy_corpus/`
  ships 48 samples (23 sycophantic + 25 genuine); F1 = 1.000 (P=1.000
  R=1.000) vs target ≥0.85, stable across operator-tuning sweep band
  `threshold ∈ {0.6, 0.7, 0.75, 0.85} × floor ∈ {2, 3}`. Primary
  `7a4e53b`; SP amendment `dceb2d8` (Q1 `_PREDICATE_PATTERNS`
  extended with 14 causal/diagnostic verbs, Q3 runtime tunable
  overrides on `classify()` + `score_corpus()` with `effective_*`
  fields, Q4a `emit_event()` gate lifted to composed verdict, Q4b
  `response_full_hash` (SHA-256 64-hex) added as first-class field,
  Q5 `_STATEMENT_WEIGHT_CAP = 2`, Q6 `_AstStats.func_body_shapes` +
  `corrective_same_name` count).

- **module_10 — release close.** This entry, version triple bump
  0.5.0 → 0.5.1, golden hash re-lock, annotated tag, handshake
  push-commands file. `ract --version` prints `RACT 0.5.1`.

### Added

- **Three new ADRs** — ADR-0040 (T8 PROMPT_DRIFT termination cause +
  operator-signed intent-recompile), ADR-0041 (SubstrateLoop shim
  closure four-decision bundle), and ADR-0042 (sycophancy v2
  tuning band -- `NULL_OP_SCORE_THRESHOLD = 0.7` +
  `MIN_COMMITMENT_FLOOR = 3` with runtime-tunable overrides and an
  eight-cell sweep test). Six further modules carry inline
  docstring-style ADRs in their primary source files.
- **New EventKinds** in `src/ract/trace/events.py::EventKind` closed
  vocabulary — `assumption.accepted` (module_01),
  `tool.invocation.pre`, `tool.invocation.post`, `tool.invocation.refused`
  (module_05), `manifest.ledger.appended`, `manifest.ledger.refused`
  (module_07), `whisperer.contract_violation` (module_09), plus
  module_05 sandbox `unenforced_sandbox` env-audit surface.
- **`TerminationCause.PROMPT_DRIFT` (T8)** and
  **`TerminationCause.PROMPT_DIGEST_MISSING` (T9)** with pinned integer
  values 1-9 (module_04).
- **`ract intent recompile <run_id>`** CLI verb with mutually-exclusive
  `--intent-file` XOR `--intent-text` and split exit codes 2/3/4/5.
- **Rootknot schema_version 4** carrying opt-in `workspace_digest` +
  `prompt_digest` + `run_id` fields; older sidecars continue to verify
  under the v3 compatibility reader path.
- **RFC 8785 JCS canonical JSON** — `src/ract/canonical.py` public
  surface, importable as `from ract.canonical import dumps_jcs,
  loads_jcs, is_canonical, CanonicalJSONError`.
- **Ambient run_id ContextVar** at `src/ract/runtime.py` — importable
  as `from ract.runtime import bind_run_id, get_current_run_id,
  run_with_ambient`.
- **Historical Manifest Ledger** at `.ract/manifest_ledger.jsonl` +
  `.ract/manifest_snapshots/`; `src/ract/security/manifest_ledger.py`
  public API `ManifestLedger`, `verify_chain`, `proof_of`,
  `verify_proof`, `LedgerVerifyResult`, `MerkleProof`.
- **Tree-sitter polyglot backend** at
  `src/ract/parsers/tree_sitter_backend.py` with the six-language
  MVP surface and `[polyglot]` optional-dep group in `pyproject.toml`.
- **Sycophancy classifier v2** public API `classify_sycophancy_v2`,
  `score_sycophancy_corpus`, `SycophancyClassification`, `CorpusScore`,
  `MIN_COMMITMENT_FLOOR`, `NULL_OP_SCORE_THRESHOLD` re-exported from
  `ract.antilazy`.
- **~500 new tests** across `tests/unit/`, `tests/integration/`,
  `tests/property/`, `tests/security/`, `tests/architecture/`
  covering the eight closure modules.

### Extended

- **`SubstrateLoop.invoke_tool`** enforces four gates (schema, registry
  membership, arg-cap, budget) with structured `ToolInvocationRefused`;
  ambient WAL/ledger observers wired at loop entry.
- **`AssumptionRegistry`** now persists accepted assumptions to a
  crash-consistent WAL replayed on restart; existing in-memory API
  unchanged.
- **`AcceptanceSuite.digest`** and every hashed payload across
  `plan.py`, `receipt.py`, `run_fingerprint.py`,
  `reproducibility_manifest.py`, `mutation_merge_gate.py`,
  `memory/cache.py`, `memory/query_trace.py`,
  `memory/functions/contracts.py`, `memory/retrieve.py`,
  `antilazy/symgraph.py` route through `dumps_jcs` instead of
  `json.dumps(sort_keys=True)`. Grep-gate installed to prevent
  regression.
- **`LoopController.run()`** binds ambient `run_id` at entry, runs
  the T8 `_check_prompt_drift` hook per iteration, rolls back to
  `last_known_good_workspace` on drift detection, and emits
  `run.completed` with orphan-file enumeration.
- **`enforce_g5` / `enforce_g6`** now have polyglot counterparts
  `enforce_g5_dead_code_polyglot` / `enforce_g6_test_copy_paste_polyglot`
  that emit `laziness.violated` with
  `kind=dead_code_polyglot|test_copy_paste_polyglot` payload
  discriminators. Legacy Python-only paths untouched.

### Verified

- **Version triple.** `VERSION`, `pyproject.toml [project].version`,
  and `src/ract/__init__.py __version__` all equal `0.5.1`;
  `ract --version` prints `RACT 0.5.1`. Test gates:
  `test_version_matches_across_files` and
  `test_ract_version_cli_reports_aligned_identity`.
- **Golden hash re-locked** at fixed-point after all module landings +
  SP-amendment folds; locked value at tag:
  `7ba823c90711e517f954a65dcbef705f8df94eae460e6b2899d1fb15bba5f4d9`
  (was `74929aa977b717567c39de1216cbe831c5239e48ebab09f38d763102b4bddf3d`
  at v0.5.0). Shift is legitimate — canonical-bytes extension,
  JCS migration, WAL / suite-chain / ledger additions, executor
  shim closure, ambient runtime, polyglot backend, sycophancy v2 all
  land under `src/ract/` inside the digest scope.
- **Sacred spine.** Rootknot three-signature schema unchanged
  (extended, not broken — schema_version 4 carries opt-in fields
  older readers ignore). `__root_author__` audit still refuses re-
  entry. AL-1 property tests green (`tests/test_antilazy_al1.py`).
- **Closed-IP wordlist scan.** Zero hits outside the two documented
  `assets/demo.cast` deferrals. Test gate:
  `test_no_closed_ip_terms_in_tracked_files`.
- **JCS grep-gate.** Zero `json.dumps(sort_keys=True)` and zero
  `json.dumps(..., sort_keys=True)` on hash-input paths outside the
  20-entry documented allowlist. Test gate:
  `tests/architecture/test_no_sort_keys_in_canonical_paths.py`.
- **Full suite.** Green modulo known skips (see per-module gate
  scorecards in `_BUILD/ract_v0.5.1_external_review_response/` +
  `_BUILD/ract_v0.5.1_wiring_completion/`).

### Wired (v0.5.1 wiring-completion pipeline)

The 2026-08-21 8-lens audit
(`_BUILD/audit_2026-08-21/AUDIT_SUMMARY.md`) found that several v0.5.1
primitives shipped with **zero production callers** — clean-tested API
surface, but the runtime paths still called the pre-v0.5.1 shape.
The wiring-completion pipeline
(`docs/RACT_v0.5.1_WIRING_COMPLETION_SPEC.md`, modules 01-11) closes
each such gap. The re-audit at
`_BUILD/audit_2026-08-21b/AUDIT_SUMMARY_v2.md` verifies zero
CRITICAL/HIGH findings remain OPEN.

- **wiring module_01** (`c78d8b1`) — provenance and docs sync.
  CHANGELOG SHAs regenerated post-filter-repo (was: 21 fabricated
  short SHAs);  THREAT_MODEL / PROVENANCE / EVENTS / ROADMAP re-hosted
  at v0.5.1 (were: frozen at v0.4.0); ADR-0042 shipped (was: cited
  in ADR count but missing on disk). Lens B C1-C6 closed.
- **wiring module_02** (`c07f8a8`) — **wired:** `make_rootknot_v4`
  now called from `src/ract/executor/steps.py:624`; sidecar
  `provenance.py` round-trips v4 fields (`schema_version=4`,
  `workspace_digest`, `prompt_digest`, `run_id`); WAL torn-pair
  regression fixed in `assumption_registry.py`; Windows chain
  readers switched to lock-free `O_APPEND` atomicity;
  `intent_recompile` now auto-scans the workspace to avoid empty
  snapshot regression. Lens D D1-D5 closed.
- **wiring module_03** (`3d039c6`) — **wired:** tool gate chokepoint.
  `SubstrateLoop.invoke_tool` now called from `executor/steps.py`
  MCP `tool_call` dispatch with `ToolInvocationRefused` handling
  (was: 0 production callers). SUBSTRATE §5 chokepoint claim now
  load-bearing. Lens C C-01 closed.
- **wiring module_04** (`9d3a534`) — **wired:** `NEVER_PASSTHROUGH`
  env allowlist. `security/sandbox_linux.py:248` and
  `security/sandbox_macos.py:152` now call `build_sandbox_env` and
  filter env against the scrubbed allowlist (was: enforced sandboxes
  bypassed the deny list entirely). SUBSTRATE §4.3 deny surface now
  active on the enforced paths, not just the Windows unenforced stub.
  Lens C C-02 closed.
- **wiring module_05** (`f51af72`) — **wired:** process-group
  tree-kill. `SubstrateLoop.spawn_subprocess` wraps
  `process_group.spawn`; `_reap_active_processes` calls `kill_tree`
  from every rollback path (was: 0 production callers in `src/`).
  `_fast_forward_head` gains `soft: bool` parameter defaulting to a
  `git reset --soft` so the compensator can inspect the tree before
  discarding. Lens C C-03 + C-04 closed.
- **wiring module_06** (`6b48e58`) — **wired:** ambient run_id +
  loop-resume. `LoopController._run_with_timeout` wraps
  `executor.submit` in `run_with_ambient` (was: bare
  `ThreadPoolExecutor` at `loop_controller.py:1362` reintroduced the
  exact bug module_06 was written to close). Full loop-resume
  protocol added (`_LOOP_STATE_SIDECAR_NAME`, `on_pause`, `on_resume`,
  `resume`, `start_index` persisted, `last_known_good_workspace`
  rehydrated). `core/loop.py` chain-init `except Exception: pass`
  replaced with a narrow tri-arm handler; `SuiteChainCorruptError`
  re-raises. T8 orphan-file delete now gated on
  `allow_iter1_delete_orphans` kwarg (was: iter-1 T8 wiped tree).
  Lens G G-01 through G-08 closed.
- **wiring module_07** (`3079aa0` + `e4258b6`) — **wired:** anti-lazy
  dispatch. `_run_sycophancy_v2_check`,  `_run_polyglot_g5_g6`, and
  `_run_canonical_g1_g7_g8` now fire per iteration from
  `loop_controller.py` (was: `classify_sycophancy_v2` and
  `enforce_g5/g6_polyglot` had 0 live callers; G1/G7/G8 had no
  `enforce_gN`). Every `*GateOutcome` in `antilazy/pre_commit.py`
  carries a `rootknot_signature` validated in `__post_init__` via
  `_require_gate_signature` (raises on empty). **AL-1 is now a
  structural invariant, not a convention.** Lens E AL-E-01 through
  AL-E-04 closed.
- **wiring module_08** (`968b7e9` + `6203f60`) — **wired:** memory
  index watchers. `SymbolIndexWatcher` now holds a cache handle and
  `_reindex_write` / `_reindex_delete` call `cache.invalidate_by_file`
  with TTL (was: silent staleness after first save). Watcher
  constructor accepts `graph_populator` + `semantic_index` and
  cascades on every reindex with per-index counters +
  `memory.freshness_gap` event. `budget_registry
  .get_with_capability_clamp` narrows via `apply_runtime_narrowing`.
  Probe scheduler fires once per `run()`;
  `_run_composed_retrieval` dispatches composition. Lens E MEM-E-01
  through MEM-E-04 closed.
- **wiring module_09** (`0879ab0` + `a061f3d`) — JCS + EventChain +
  ledger tamper. Three real hash-input sites migrated to `dumps_jcs`
  (`plan_replay.py`, `memory/repo_fingerprint.py`,
  `memory/probes/scheduler.py`); remaining sites documented as
  human-report/storage-only in the JCS grep-gate allowlist; the gate
  now also forbids `sha256(json.dumps(sort_keys=True))` +
  `.encode(...)` on hash inputs. `EventChain` no longer resets on
  fresh writer construction —  `writer.py::_reseed_tip_from_disk`
  walks the tail, seeds from the last parseable event, refuses on
  UTF-8 decode failure. `EventReader.load` / `iter_events` now
  tail-tolerant + middle-strict + WARN (was: only ledger that
  hard-failed on truncated tail). `manifest_ledger._build_entry`
  stamps `entry_index`; `verify_chain` detects middle-excise via
  physical-vs-stamped density check. Lens F H1-H4 + Lens G G-06
  closed.
- **wiring module_10** (`427537c` + `53280ff`) — UX + CLI + retrieval
  wire + `.ract`/`.rack` unification + manifest-ledger CLI verbs.
  Full-verb `ract --help` catalog via `cli_help.py`;
  `workspace_state.migrate_rack_to_ract` idempotent migration at CLI
  entry; `ract retrieval query` now calls the real `retrieve()`
  primitive (was: documented stub); `ract manifest ledger
  {verify,inspect,show,proof}` verbs added; duplicate marketplace
  dispatch deleted (tombstone comment kept); `--auto` refuses on
  non-TTY stdin with exit 3; bare `ract retrieval` / `memory` /
  `plan` exit 0 after help; README verb index regenerated + drift
  gate; module_02 executor test fixture updated to full v4 dep set;
  distinct exit codes for `verify` chain-valid / broken / crashed.
  Lens A C1-C3 + M1-M9 closed.
- **wiring module_11** (this commit) — release close. Golden hash
  re-locked; 8-lens re-audit at
  `_BUILD/audit_2026-08-21b/AUDIT_SUMMARY_v2.md` verifies zero
  CRITICAL/HIGH findings remain OPEN; `v0.5.1` tag re-issued at the
  wired HEAD (prior `bb8e013` preserved as
  `backup-v0.5.1-preWiring`); `HANDSHAKE_PUSH_COMMANDS.md` written
  for operator-gated push.

### Not yet shipped in v0.5.1 (deferred to v0.6)

The 2026-08-21 source-spec audit
(`_BUILD/audit_2026-08-21c/AUDIT_SUMMARY_c.md`) surfaced a gap
between what the Memory Discipline spec
(`docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`) prescribes and what
v0.5.1 actually ships. The v0.5.1 spec-completeness pipeline
(`docs/RACT_v0.5.1_SPEC_COMPLETENESS_SPEC.md`) addresses the
release-label honesty gap by naming every prescribed mechanism that
is **not** shipping in v0.5.1, so readers do not have to grep the
tree to discover the deferral:

- **DSPy signature compilation-recompilation** (Memory Discipline
  spec §Self-Adjustment Mechanisms item 3, v0.6-backlog line 70)
  is **not shipped in v0.5.1**. No `src/ract/compilation/` directory;
  no `signatures.py` or `training.py`; the `dspy` dependency is not
  present in `pyproject.toml`. Deferred to v0.6 per **ADR-0043**.
  The substrate the mechanism will consume (probes, failure
  records, repo fingerprint, JCS canonical hashing, event trace)
  is production-live.
- **LeWM 23-dim behavioral-vector drift detection** (Memory
  Discipline spec §Self-Adjustment Mechanisms item 4,
  v0.6-backlog line 72; also referenced as an emit field in
  §Operational Metrics) is **not shipped in v0.5.1**. No
  `src/ract/observability/` package; no `lewm.py`, `drift.py`, or
  `spc.py`; no SPC statistics harness; no drift-alert path. Zero
  source hits for `lewm` / `LeWM` / `23-dim`. Deferred to v0.6
  per **ADR-0044**. The substrate (event trace, per-repo capability
  record, per-repo fingerprint, failure-record aggregation) is
  production-live.
- **`verify` / `review` / `commit` / `document` memory-discipline
  functions** (Memory Discipline spec §Function contracts;
  v0.5.0 shipped `intake` / `research` / `plan` / `edit`) remain
  deferred per ADR-0036 and ADR-0037. Loop composition today runs
  the four v0.5.0 verbs; the four deferred verbs are v0.6 scope.
- **Cross-function grouping rules** (Memory Discipline spec
  §Cross-Function Grouping — dataclass+methods, trait+impls,
  test+subject, fn+type-aliases). Not yet shipped in v0.5.1;
  addressed by module_04 of the v0.5.1 spec-completeness pipeline
  (pending).
- **Language chunkers for Java / Kotlin / C# / C / C++** (Memory
  Discipline spec §AST Chunking Rules). v0.5.1 ships chunkers for
  Python / TypeScript / Rust / Go (four of the ten spec languages);
  the remaining five are deferred to v0.6.
- **SUMMARY-format chunk generation + Bonsai council fallback**
  (Memory Discipline spec §Chunk Overflow). Today `format_chunk`
  returns a placeholder for the SUMMARY format; real summarisation
  is pending in module_05 of the v0.5.1 spec-completeness
  pipeline.
- **Nightly failure-learning job + human-review queue + retrieval-
  strategy adjustment surface** (Memory Discipline spec
  §Failure Learning items 3-5). Aggregation ships; the nightly
  scheduler and operator-review queue are pending in module_06 of
  the v0.5.1 spec-completeness pipeline.
- **Verifier availability pre-check** (`predicate.available(snapshot)`
  gate before loop entry), **SubagentHandle wired to compensator
  stack** (cascade-on-halt for subagent-shaped operations), and
  **`index_digest()` equivalence-based no-op-rebuild short-circuit
  on the 3 indexes** (v0.2-primitive salvage items). Pending in
  module_07 of the v0.5.1 spec-completeness pipeline.
- **`refuse_if_over_max` production wire-in** and
  **`state_context` 15% sub-budget cap** (Memory Discipline spec
  §Budget Declaration + §Context Composition). Both primitives
  exist; wiring is pending in module_02 of the v0.5.1
  spec-completeness pipeline.
- **Write-first-invariant hardening in `JsonlEventWriter` +
  `trace/repair.py` deterministic repair module** (v0.2-primitive
  §5.1.2 / §5.1.3 salvage). Pending in module_03 of the v0.5.1
  spec-completeness pipeline.

### Known limitations (carried to the v0.6 hardening backlog)

The nine external-review-response modules each queued their own
`## Flagged gaps` roll to v0.6. The load-bearing items:

- **POSIX dir-fsync + one-instance-per-dir enforcement for WAL
  rotation** (module_01). Rotation is atomic within a single instance;
  concurrent-writer safety across `os.replace` boundary defers to v0.6.
- **UTF-16 code-unit sort upgrade for JCS.** RFC 8785 specifies
  UTF-16 code-unit sort; current implementation uses codepoint sort.
  Byte-identical output on the ASCII path; non-BMP disagreement
  surfaces on v0.6 fuzz corpus (module_03).
- **Merkle-of-JCS-lines for JSONL ledgers** (module_03). JSONL ledgers
  hash each line under JCS but no per-line Merkle summary; a v0.6 rot
  audit reads the whole file.
- **HMAC operator key → Ed25519 with revocation ceremony**
  (module_04). Current HMAC-SHA256 matches the stated threat model
  (possession-only); Ed25519 upgrade + revocation flow defer to v0.6.
- **Push-time compensator escalation** (module_05). `check_pushed`
  refuses compensation on pushed commits; the operator-facing
  escalation path (RFC-signed override) defers to v0.6.
- **Env allowlist Merkle attestation** (module_05). Env passthrough
  logged count-only; per-name attestation defers to v0.6.
- **EventChain prev_hash reset on fresh writer** (module_06). A
  freshly-instantiated writer resets the chain-head pointer; the
  pre-existing invariant is exposed by the ambient path but was not
  introduced by v0.5.1.
- **Ledger rotation with roll-forward Merkle tie** (module_07). The
  ledger is single-file append-only; rotation-with-roll-forward-
  hash-tie defers to v0.6.
- **Ed25519-signed ledger appends** (module_07). Current appends
  are covered by the run_id + manifest_digest binding in the signed
  Rootknot canonical bytes; a per-append signature defers to v0.6.
- **Consolidate two Python dead-code detectors** (module_08). Legacy
  `enforce_g5` and new `dead_code_polyglot` both cover Python; a
  single detector routed by extension defers to v0.6.
- **Grammar-version pin ADR** (module_08). Tree-sitter grammars pin
  via `pyproject.toml` version specifiers; an ADR documenting the
  pin policy defers to v0.6.
- **Dense one-liner boundary case** (module_09). Pure single-liner
  function response with no prose lands at floor 1; adding a
  "function body non-empty AND response body non-empty" bump
  defers to v0.6.
- **`retrieval_attestation` run-context binding.** Carried from the
  v0.5.0 CHANGELOG "Known limitations" section. Module_02's
  Rootknot canonical-bytes extension partially closes it (the new
  `run_id` field is now bound into the signed surface); a unified
  payload that folds `prompt_digest` + `workspace_digest` INTO the
  `retrieval_attestation` bundle-hash context defers to v0.6.
- **Regex fallback F1 gate for sycophancy v2** (module_09). The
  regex fallback path lacks its own corpus gate; a "fallback corpus"
  subset that force-flips `used_regex_fallback` to True defers to
  v0.6.

Deferred from the wiring-completion pipeline (see
`_BUILD/ract_v0.5.1_wiring_completion/module_XX.md`):

- **8 doc footers still carry pre-v0.5.1 stamps** (wiring Lens B M3
  residual). Four of twelve older docs were bumped to a v0.5.1
  footer; the rest keep their v0.1.1 / v0.2.0 / v0.4.0-rc1 stamps
  because their content did not change materially. A bulk footer
  refresh defers to v0.6.
- **`index.md` framing** (wiring Lens B M4 residual). The doc index
  CHANGELOG link + footer land at v0.5.1 but the v0.3 framing +
  solo v0.2.0 release-note link remain.
- **`RACT_v0.4.1_INTENT_FIDELITY_SPEC.md` and
  `RACT_v0.5.0_PRE_PUSH_CLEANUP_SPEC.md`** (wiring Lens B M8 OPEN)
  are cited in older CHANGELOG entries but not present under
  `docs/`. Reconstruction defers to v0.6.
- **Manifest-ledger `verify_chain` external anchoring** (wiring
  Lens F H4 SP Q3 PARTIAL residual). The physical-vs-stamped-index
  density check catches naive middle-excise; a full-recompute + a
  correlated tail-truncate + pre-module_09 excise class still
  require external anchoring (Merkle root pinned in a signed
  Rootknot). Documented in `verify_chain` docstring; defers to v0.6.
- **Loop-controller L1/L2/L3 low-severity items** (wiring Lens G
  G-09/G-10/G-11) — `OSError` transparency in a specific error
  path, dup-digest short-circuit micro-optimisation, and
  `check_t2` docstring polish. Non-blocking.

Complete Flagged gaps roll per module is preserved in the pipeline
fragments at `_BUILD/ract_v0.5.1_external_review_response/module_0N.md`
and `_BUILD/ract_v0.5.1_wiring_completion/module_0N.md`.

## [0.5.0] - 2026-08-19 — Memory Discipline

Minor release for the Memory Discipline pipeline
(`_BUILD/ract_v0.5.0_memory_discipline/`). This release installs a new
memory substrate on top of v0.4.1: a token budget accountant with a
hard ceiling, three query indexes (symbol / graph / semantic), a
four-level retrieve primitive with cascade + query cache, four
function contracts (intake / research / plan / edit), four playbooks
carrying compositions of those functions, three self-adjustment probes
(needle / coherence / adherence) with per-repo capability fingerprint,
and integration wiring into the existing SubstrateLoop and Rootknot
schema. Tag is `v0.5.0`. Nine ADRs (ADR-0031 through ADR-0039) name
the load-bearing decisions.

### Per-module surface

- **module_01 — token budget system.** `src/ract/memory/budget.py`
  ships `BudgetAccountant` + `BudgetDeclaration` with hard-ceiling
  refusal, composition override, and runtime narrowing;
  `budget_defaults.yaml` defines defaults for the four v0.5.0
  functions; ADR-0031 names the ceiling policy.
- **module_02 — symbol index.** `src/ract/memory/symbol_index.py` with
  SQLite schema at `symbol_index_schema.sql`, tree-sitter parsers for
  Python / TypeScript / Rust / Go under `memory/languages/`, and an
  incremental file watcher at `watcher.py`; ADR-0032.
- **module_03 — graph index.** `graph_index.py` with SQLite edge
  schema, `multilspy` LSP client at `lsp.py`, `lsp_fallback.py` for
  when a language server is not installed, and a query API covering
  callers / callees / blast_radius / path / orphans / hotspots;
  ADR-0033.
- **module_04 — semantic index.** `semantic_index.py` backed by a
  LanceDB store at `.rack/index/semantic/`, `bge-small-en-v1.5` as the
  default embedding, and a token-bounded search API; ADR-0034.
- **module_05 — retrieve primitive.** `retrieve.py` with a four-level
  cascade (symbol → graph → semantic → best-effort), `cache.py`
  keyed on `(query_hash, repo_commit_hash)`, `chunk.py` formatter with
  four formats (FULL / BODY_ONLY / SIGNATURE / SUMMARY), and
  `query_trace.py` for observability; ADR-0035.
- **module_06 — function contracts.** `memory/functions/` package
  ships `intake.py`, `research.py`, `plan.py`, `edit.py` with typed
  contracts, prompts under `functions/prompts/`, a mock provider under
  `functions/testing/`, and a session context at `memory/session.py`;
  ADR-0036.
- **module_07 — playbook composition.** Four YAML playbooks
  (`refactor_rename`, `refactor_extract`, `bug_fix`, `unit_test`)
  under `memory/playbooks/`, `composition_runner.py` orchestrating
  the four-function stack per playbook step, and `composition.py`
  primitives; ADR-0037.
- **module_08 — self-adjustment probes.** Three probes
  (`needle`, `coherence`, `adherence`) under `memory/probes/` with
  `scheduler.py` per-repo dispatch, `failure_records.py` aggregation,
  and `repo_fingerprint.py` for per-repo capability persistence at
  `.rack/probes/capability.json`; ADR-0038.
- **module_09 — integration with existing RACT.** Seven new EventKind
  members (`budget.declared`, `budget.exceeded`, `retrieval.requested`,
  `retrieval.satisfied`, `retrieval.cascaded`, `retrieval.refused`,
  `probe.evaluated`) added to `trace/events.py`; `SubstrateLoop`
  reads `SubstrateStepSpec.metadata["retrieval_bundle"]` and emits a
  paired `retrieval.satisfied` event; `Rootknot` generator payload
  gains optional `retrieval_attestation`; ALM `enforce_g6` +
  `enforce_g7` accept `CandidateDiff | None`; `ract memory init`,
  `ract memory apply-narrowings`, and `ract retrieval query` land as
  CLI subverbs; ADR-0039.
- **module_10 — release close.** This entry, version triple bump
  0.4.1 → 0.5.0, ROADMAP compilation, combined 56-signal sweep, tag.

### Fixed (memory-discipline)

Fix commits landed in this pipeline (all under
`memory(v0.5)` and identified by short SHA):

- `86583f2` memory(v0.5): fix module_01 auction allowlist for
  pre-wired helpers.
- `5b62a21` memory(v0.5): re-lock golden hash for module_01
  additions.
- `9bc0bb6` memory(v0.5): allowlist module_02 imports in
  public-provenance test.
- `b38a425` memory(v0.5): fix module_02 SP findings Q1+Q2 —
  type-alias and let-arrow chunking.
- `ede85a9` memory(v0.5): fix module_03 SP findings Q1+Q3 —
  atomicity docstring + probe.
- `d97d50b` memory(v0.5): fix module_04 SP findings Q1+Q3 +
  closed-IP scan.
- `b8bb510` memory(v0.5): fix module_07 SP findings Q2+Q3 + POST
  chains + hash re-lock.
- `72a83d3` memory(v0.5): untrack `_BUILD/` pipeline scratch
  (gitignored per convention).

Modules 04-09 also folded Second-Pass regression tests INTO the
main landing commit (no separate fix commit) per each module's
Second Pass log; the module fragments record the fold decisions.

### Added

- **`src/ract/memory/` package** — 30+ Python modules covering budget
  accountant, three indexes, retrieve primitive, four function
  contracts, playbook composition, and three self-adjustment probes.
- **Four playbooks** — `refactor_rename.yaml`, `refactor_extract.yaml`,
  `bug_fix.yaml`, `unit_test.yaml` under
  `src/ract/memory/playbooks/`. Eight further playbooks defer to v0.6.
- **Four function prompts** — `intake_v1.md`, `research_v1.md`,
  `plan_v1.md`, `edit_v1.md` under
  `src/ract/memory/functions/prompts/` gated by
  `verify_prompt_coverage` at import time.
- **Budget defaults** — `src/ract/memory/budget_defaults.yaml` with a
  declaration per v0.5.0 function.
- **Two SQL schemas** — `symbol_index_schema.sql` and
  `graph_index_schema.sql`.
- **Seven new event kinds** in `src/ract/trace/events.py::EventKind`:
  `budget.declared`, `budget.exceeded`, `retrieval.requested`,
  `retrieval.satisfied`, `retrieval.cascaded`, `retrieval.refused`,
  `probe.evaluated`.
- **Nine ADRs** — ADR-0031 through ADR-0039 under `docs/ADRs/`.
- **Three CLI subverbs** — `ract memory init`,
  `ract memory apply-narrowings`, `ract retrieval query` (skeleton;
  full three-index wiring queued for v0.6 polish).
- **`docs/ARCHITECTURE.md`** — nine new sections describing each
  memory-discipline surface.
- **`docs/EVENTS.md`** — schema_version bumped 2 → 3 with the seven
  new kinds documented.
- **`tests/memory/`** — 450+ new tests across the memory-discipline
  surface; five new tests under `tests/contracts/` +
  `tests/test_release_surface.py` covering the integration wiring.

### Extended

- **`SubstrateLoop.run_step`** reads
  `SubstrateStepSpec.metadata["retrieval_bundle"]` when present and
  emits `retrieval.satisfied` per step. Absent metadata is a no-op;
  existing callers do not need to change.
- **`Rootknot` generator payload** gains an optional
  `retrieval_attestation` field; older sidecars continue to verify
  under the v2 compatibility reader path. No signature added, no
  schema-version bump.
- **ALM `enforce_g6_edit` and `enforce_g7_edit`** land as edit-path
  gate helpers.
  `enforce_g6_edit(diff: CandidateDiff | None, plan, *, step_id=None)`
  raises `LazinessViolatedError(kind="diff_without_plan")` when
  `diff is None`, so a caller cannot silently bypass the under-edit
  closure gate; legacy callers reach `enforce_g6(transaction, graph,
  edited_symbols)` instead.
  `enforce_g7_edit(diff: CandidateDiff, companion, *, step_id=None)`
  requires a non-Optional `CandidateDiff` and raises
  `LazinessViolatedError(kind="companion_flagged")` when the companion
  provider rejects the review.
  Path normalization at `_normalize_file_path` closes the
  backslash / leading-dot-slash Second-Pass finding.
- **`ract` CLI** learns `memory` and `retrieval` subverbs via the
  existing dispatch layer; existing verbs untouched.
- **`docs/ARCHITECTURE.md`** gains nine new sections; every ADR-0031
  through ADR-0039 named in the ADR comment lines.

### Verified

- **56-signal sweep.** 11 REBUILD + 16 SUBSTRATE + 16 ALM + 13 new
  MEMORY signals all evaluate true at the tag commit via
  `pytest -q tests/test_release_surface.py`.
- **Per-module attestations.** Nine memory-discipline modules each
  ship a Second Pass log + POST-audit chains + Flagged gaps section.
  Test gate: `test_roadmap_carries_memory_discipline_module_gaps`.
- **Sacred spine tests.** Rootknot three-signature schema unchanged;
  `__root_author__` audit still refuses re-entry; AL-1 property tests
  green.
- **Closed-IP wordlist scan.** 25 terms; zero hits outside the two
  documented `assets/demo.cast` deferrals. Test gate:
  `test_no_closed_ip_terms_in_tracked_files`.
- **Version triple.** `VERSION`, `pyproject.toml [project].version`,
  and `src/ract/__init__.py __version__` all equal `0.5.0`;
  `ract --version` prints `RACT 0.5.0`. Test gates:
  `test_version_matches_across_files` and
  `test_ract_version_cli_reports_aligned_identity`.
- **Golden hash re-locked** at fixed-point after every landing +
  Second Pass fold; locked value at tag:
  `2905a2b789aa9900398de7ce6924d32919dd532618a835c118841c8c3826b8b0`.
- **Baseline pre-existing failures from v0.4.1 remain fixed** at the
  v0.5.0 tag (four failures triaged and closed at v0.4.1 release
  close; verified green here).

### Known limitations (carried to the v0.6 hardening backlog)

Module_09 explicitly deferred 19+ inbound integration constraints
from modules 01-08 POST chains to v0.6, on the judgment that
module_09 ships the integration *shape* while v0.6 ships the
*polish*. The load-bearing deferrals are:

- **`retrieval_attestation` run-context binding (deferred to v0.5.1).**
  The new `retrieval_attestation` field on the Rootknot generator
  payload binds the retrieval bundle bytes but not the surrounding
  run context. A valid signed knot can carry a byte-authentic bundle
  attestation unbound to the `run_id`, `prompt_hash`, or
  `workspace_snapshot_digest` under which it was produced, so a bundle
  can be replayed into a different run context. Same replay-attack
  vector the DeepSeek REVIEW_2 external-review pass identified during
  Memory Discipline Rootknot review; the new field arrives with the
  weakness rather than the fix. Unified-payload extension
  (`run_id` + `prompt_hash` + `workspace_snapshot_digest` folded into
  the signed surface) is queued as a v0.5.1 blocker.
- **Three-index CLI query wiring.** `ract retrieval query` lands as a
  CLI skeleton; the actual retrieve primitive is invoked programmatically
  from `SubstrateLoop`. Wiring the CLI subverb to the three indexes
  end-to-end defers to v0.6.
- **Provider bridge for MemoryFunctionProvider.** The four function
  contracts are called via a mock provider in tests; wiring the real
  provider adapter to production `LlmProvider` defers to v0.6.
- **SUMMARY chunk-format provider adapter.** Retrieve emits
  SUMMARY-format placeholder text; a real summarization provider
  hook defers to v0.6 (module_05 gap #2 / module_06 gap #9).
- **`verify_prompt_coverage` startup wiring.** The gate runs at
  import time inside `prompts_loader`; wiring it to a startup-time
  RACT invocation check defers to v0.6.
- **`probe_lancedb` startup probe.** LanceDB availability check runs
  on first index touch; a startup-time probe defers to v0.6.
- **`current_budgets` from probes.** Probes emit
  `probe.evaluated` events; feeding probe outcomes back into
  `current_budgets` per function defers to v0.6.
- **`PhaseRecord` token counts.** PhaseRecord carries an outcome but
  not the token counts consumed by each phase; wiring the estimator
  to write token counts per phase defers to v0.6
  (module_08 gap #4).
- **Wall-clock `update_file` guard.** Retrieve's update_file path is
  guarded by a call-count budget, not a wall-clock budget
  (module_05 gap #4).
- **LSP language dispatch.** `composition_runner._run_edit_single`
  groups by file path; the LSP dispatch per language defers to
  v0.6 (module_07 gap #1).
- **`composition_runner` as `ract run`.** Composition is exposed
  programmatically; wiring it as the default runner behind
  `ract run` defers to v0.6.
- **Playbook budget overrides.** Playbooks parse `retrieval_overrides`
  at YAML load; forwarding full `RetrievalQuery` shape defers to v0.6
  (module_07 gap #4).
- **`plan.mid_invocation_queries`.** Plan phase queues mid-invocation
  retrieval queries; the runner does not yet re-run retrieve on each
  such query (module_07 gap #4 pair).
- **Noise-tolerant needle reducer** (module_08 gap #1).
- **`mkstemp` tmp-file leak on SIGKILL** in atomic-replace paths
  (module_08 gap #2).
- **Fallback-reference inflation** in adherence probe when the
  operator's rejected proposal itself references a fallback
  (module_08 gap #3).
- **Coherence-probe semantic-diff** — probe compares hashes not
  semantic overlap (module_08 gap #5).
- **Adherence-probe placement variants** — probe accepts the operator's
  proposal at any position (module_08 gap #6).
- **Fingerprint git-log purity** — probe reads git log fields that are
  not strictly deterministic under concurrent commits (module_08 gap #7).
- **Second-Pass prompt-must-inline-source convention.** Module_08 SP
  first attempted a description-only prompt and got fully hallucinated
  verdicts. The convention is now: inline the source bundle in every
  SP prompt for release-surface changes. Documented as inbound
  constraint to module_09 pipeline dispatch (module_08 gap #8).

All items compiled into `docs/ROADMAP.md` under
`## v0.6 hardening (from memory-discipline module_0N)` sections
per module.

## [0.4.1] - 2026-08-17 — Intent-Fidelity

Patch release for the Intent-Fidelity pipeline
(`_BUILD/ract_v0.4.1_intent_fidelity/`, patch-versioned per semver since
the pipeline delivered drift-audit and fix commits only, no new features
and no breaking changes). This release verifies that seven prior eras' stated
intents still hold as actual behavior of the current tree and lands fix
commits for drift the audits found. Tag is `v0.4.1`.

### Verified (intent-fidelity by era)

- **v0.1.x era (module_01).** Nine intent statements: 6 PERSISTS, 2 PARTIAL,
  1 DRIFTED. Trust and tooling surface (dead-code auction, Fence,
  consolidation pass, rot report, provider routing) audited against the
  current tree; drift closed with fix commits. See
  `_BUILD/ract_v0.4.1_intent_fidelity/module_01.md` for the per-statement
  verdict rollup.
- **v0.2.0 REBUILD era (module_02).** Nine intent statements: 7 PERSISTS,
  2 PARTIAL. Signed Rootknot origin, RK-1 and RK-2 invariants, assumption
  registry, T1-T7, threat model, versioned plan schema, eval harness first
  cut audited. Both PARTIAL verdicts routed to ROADMAP with substrate-era
  owners.
- **v0.3.0 REBUILD era (module_03).** Ten intent statements: 10 PERSISTS.
  Auditability and depth surface (`PROVENANCE.md`, independence lint,
  benchmark harness, `SessionKey.rotate`, provenance verify CLI, executor
  wiring) audited clean; two fix commits landed for module_02 carry-forward
  gaps.
- **v0.4.0 SUBSTRATE era (module_04).** Sixteen §11 signals: 12 PERSISTS,
  4 PARTIAL (signals 4, 5, 9, 10 sharing one architectural root cause: the
  executor-adapter shim constructs SubstrateLoop without manifest /
  sandbox_backend / event writer). One fix commit landed for the v0.3
  provenance-verify silent-partial gap.
- **v0.4.0 ALM era (module_05).** Sixteen §13 signals: 6 PERSISTS, 10
  PARTIAL. All ten PARTIAL share the same architectural root cause as
  SUBSTRATE 4/5/9/10 (no runtime path plumbs run_id + workspace-root
  through the loop). One fix commit extended the AL-1 property test to
  enumerate all three sub-clauses independently.
- **v0.4.0-rc1 audits era (module_06).** Six intent statements: 5
  PERSISTS, 1 PARTIAL note-only (CHANGELOG retag-addendum cite stale by 11
  commits; tag body itself clean). One fix commit generalized two residual
  filename references and pinned a wordlist regression gate at
  `tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files`.
- **Restoration clusters 1 + 2 era (module_07).** Eleven intent statements:
  10 PERSISTS, 1 PARTIAL note-only (primitive lands with 4 green tests but
  zero consumers; a genuine None-vs-unpassed ambiguity is required at a
  callsite before adoption is warranted). Zero fix commits — all persistence
  paths are behavior-gated and hold.

### Fixed (intent-fidelity)

Ten fix commits landed in this pipeline under `intent-fidelity(v0.5): fix`:

- `755578f` intent-fidelity(v0.5): fix — merge-gate `_score` reads current
  value not delta (module_01).
- `f4598ed` intent-fidelity(v0.5): fix — restore `ract manifest` alias for
  `repro-manifest` (module_01).
- `ceeef12` intent-fidelity(v0.5): source-tree golden hash re-lock after
  fix commits (module_01).
- `84ece29` intent-fidelity(v0.5): fix — `ai-sbom` accepts current-shape
  `Receipt` (module_03, closing module_02 punt gap).
- `fdd7474` intent-fidelity(v0.5): fix — `PROVENANCE.md` names v0.4
  extended attestations (module_03).
- `9e56078` intent-fidelity(v0.5): source-tree golden hash re-lock after
  module_03 fix commits.
- `881c5ee` intent-fidelity(v0.5): fix — `provenance verify` names unset
  v2/v3 extended fields (module_04, closing module_03 gap 2).
- `b6cc908` intent-fidelity(v0.5): source-tree golden hash re-lock after
  module_04 fix.
- `bfecde4` intent-fidelity(v0.5): fix — AL-1 property test enumerates all
  three sub-clauses independently (module_05).
- `9e6d0f9` intent-fidelity(v0.5): fix — generalize residual dispatcher-name
  filename references plus pin wordlist regression gate (module_06).

Plus, at module_08 release close:

- `intent-fidelity(v0.5): fix` — carried-forward gaps + pre-existing test
  failures (QUICKSTART template scrub, `plan analyze` vs. spec `plan risk`
  naming drift, CHANGELOG retag-addendum cite refresh, four pre-existing
  test failures triaged: two G7/G8 date-drift fixtures refreshed, one
  dead-code allowlist entry for `sentinels.py`, one README `evals/README.md`
  reference).
- `release(v0.5.0)` — initial release-close commit: VERSION triple bump,
  release-surface test refresh, initial `[0.5.0]` CHANGELOG entry, README
  refresh, ROADMAP compiled from every era. Version was corrected to
  `0.4.1` by the pivot commit below per semver (drift-audit plus fix
  commits, no new features and no breaking changes → patch, not minor).
- `release(v0.4.1)` — semver pivot: VERSION triple `0.5.0` → `0.4.1`,
  CHANGELOG heading `[0.5.0]` → `[0.4.1]`, ROADMAP labels
  `v0.6 hardening` → `v0.5 hardening`, tag `v0.5.0` retagged as
  `v0.4.1` on the pivot commit.

### Verify

- 43-signal sweep: 11 REBUILD + 16 SUBSTRATE + 16 ALM. Every signal
  evaluates true at the tag commit via
  `pytest -q tests/test_release_surface.py`.
- Per-module intent-fidelity attestations: seven modules, one
  `## Intent verification results` section per module fragment. Test
  gate: `test_intent_fidelity_module_attestations_logged`.
- Closed-IP wordlist scan: 25 terms, zero hits outside the two documented
  deferrals in `assets/demo.cast`. Test gate:
  `test_no_closed_ip_terms_in_tracked_files`.
- Version triple: `VERSION`, `pyproject.toml [project].version`, and
  `src/ract/__init__.py __version__` all equal `0.4.1`; `ract --version`
  prints `RACT 0.4.1`. Test gate: `test_version_matches_across_files` and
  `test_ract_version_cli_reports_aligned_identity`.

### Known limitations (carried to the v0.5 hardening backlog)

- **Ten ALM PARTIAL signals share one shim-wiring root cause.** ALM signals
  1-10 plus signal 16 (module_05) and SUBSTRATE signals 4, 5, 9, 10
  (module_04) all lack the same architectural piece: the executor-adapter
  shim constructs `SubstrateLoop` without a `CapabilityManifest`, a
  `SandboxBackend`, or a `JsonlEventWriter`, so no runtime path plumbs
  `run_id` + workspace-root through the loop and the ten anti-lazy report
  files never land under `evals/runs/<run_id>/`. Fixture-only coverage
  holds; the runtime side is v0.5 hardening scope (see
  `docs/ROADMAP.md::v0.5 hardening (from substrate close)` and
  `::v0.5 hardening (from intent-fidelity module_04/05)`).
- **`sentinels.py` primitive holds without a consumer callsite** (module_07
  statement 5 PARTIAL). The `MISSING` sentinel is production-ready but no
  current API surface has the None-vs-unpassed ambiguity that motivates
  adoption. Consumer-site migration is v0.5 scope, gated on new-surface
  need.
- **11 Flagged gaps carried forward from intent-fidelity modules 01-07.**
  See `docs/ROADMAP.md` v0.5 hardening sections.

## [0.4.0] - 2026-07-26 — Substrate + Anti-Lazy (v0.4.0-rc1)

Combined release close for the SUBSTRATE pipeline (`_BUILD/ract_v0.4.0_substrate/`)
and the Anti-Lazy Module (ALM) pipeline (`_BUILD/ract_v0.4.0_antilazy/`). Tag is
`v0.4.0-rc1`; the `rc1` suffix reflects that the ALM code is new and the combined
release surface warrants a candidate cycle before the `v0.4.0` final tag. Every
new CLI verb, every new invariant, every new event kind, and every new config
option added by either pipeline appears in the bullets below.

### Added (substrate)

- **AcceptanceSuite + IntentCompiler + T1 rewrite (module_01, ADR-0010).**
  `AcceptanceSuite`, `AcceptancePredicate`, and `IntentCompiler.compile` land in
  `src/ract/core/`. Every run commits `evals/runs/<run_id>/suite.json`. Loop
  termination T1 reads: all required predicates evaluate true against the final
  snapshot. `LoopState` refuses zero-required-predicate suites.
- **Worktree-per-step transactional execution (module_02, ADR-0011).**
  `StepTransaction` + `TransactionOutcome` in `ract.core.transaction`;
  `WorktreeManager` in `ract.executor.worktree`; `SubstrateLoop` in
  `ract.executor.loop`. `HandshakeRegistry.blocks_commit` blocks dependent
  commits at the git layer. New CLI verbs: `ract session ls`,
  `ract session diff <step_id>`.
- **Capability manifest + OS-enforced sandbox (module_03, ADR-0012 + ADR-0013).**
  `CapabilityManifest` + `ManifestValidator` + `ManifestDigest` in
  `src/ract/security/manifest.py` (Pydantic v2 promoted to a runtime
  dependency). `LinuxSandbox` (Bubblewrap + Landlock + seccomp-bpf) +
  `MacosSandbox` (Seatbelt / sandbox-exec) + `SandboxBackend` protocol.
  `StepTransaction` accepts a `manifest` and carries `manifest_digest`.
  `--yolo` semantics changed to "auto-widen within pre-declared bounds"
  gated on `HandshakeRegistry.widen_manifest_for`. New adversarial
  `tests/security/` corpus.
- **Typed action union + conformance corpus + provider gate (module_04,
  ADR-0014).** Closed 8-kind `Action` discriminated union in
  `src/ract/core/actions.py` with path-traversal guards and `extra="forbid"`.
  Three schema converters in `src/ract/providers/schema.py`
  (`to_openai_structured_outputs`, `to_anthropic_tool_use`,
  `to_json_schema_fallback`). `ResponseValidator` with two-strike halt
  hooked to `TerminationCause.PROVIDER_TIMEOUT`. `evals/conformance/`
  (68 fixtures: schema_compliance + tool_discipline + refusal_fidelity).
  New CLI verb: `ract conformance run --provider <name>`. Router gates
  registration on a passing recent conformance report.
- **Event trace: hash-chained log + OTel export + trace CLI (module_05,
  ADR-0015).** Closed 24-kind `EventKind` vocabulary +
  hash-chained `EventChain` in `ract.trace.events`. `JsonlEventWriter` at
  `evals/runs/<run_id>/events.jsonl`. `OtlpExporter` mirrors events as
  OpenTelemetry spans per GenAI Semantic Conventions. New CLI verbs:
  `ract trace replay`, `ract trace fork`, `ract trace diff`,
  `ract trace to-test`. `docs/EVENTS.md` published (`schema_version: "1"`,
  later bumped to `"2"` in module_06 to add `auction.proposal`).
  `RunReporter` becomes a projection over the event stream.
- **Rootknot re-oriented to environment attestation (module_06, ADR-0016).**
  `Rootknot` extended with `environment_signature`, `acceptance_suite_digest`,
  `predicate_results`, `manifest_digest`, and `schema_version`. **Invariant
  RK-3 (Environmental Attestation)** landed in `verify_workspace` with
  four sub-clauses. Sidecar reader dispatches on `schema`: `sidecar/v1`
  verifies under RK-1 + RK-2 only (RK-3 skipped with `DeprecationWarning`);
  `sidecar/v2` embeds the raw sandbox pubkey (base64) for offline verify.
  `SandboxKey` in `src/ract/security/keys.py`.
- **Whisperer / Fence / Auction contracts (module_06, ADR-0017).** New
  `src/ract/contracts/` package: `WhispererContract` (pre-plan dialect-brief
  injection with per-snapshot cache), `FenceGate` (pre-delete gate with
  single-use ticket admitted by `open_transaction`; `UnfencedDeleteError`
  is the structural refusal), `AuctionSweep` (between-iteration schedule
  gated by `min_iteration_wall_seconds`). New event kind
  `auction.proposal` added to the closed vocabulary; `docs/EVENTS.md`
  `schema_version` bumped 1 → 2.
- **External eval anchors: Aider Polyglot + SWE-bench Lite + LEADERBOARD
  (module_07, ADR-0018).** 10-problem Aider Polyglot subset
  (`evals/polyglot/subset.json`); 5-instance SWE-bench Lite pin
  (`evals/swe_bench_lite/instances.json`) spanning django, pytest, sympy.
  `evals/LEADERBOARD.md` is the canonical published record;
  `evals/leaderboard/update.py` regenerates it idempotently.
  `.github/workflows/evals-full.yml` nightly workflow gated by
  `RACT_EVAL_ENABLED`.
- **SubstrateLoop-as-CLI-default via executor-adapter shim (module_08
  substrate close, `substrate_loop` config flag).** `src/ract/executor/substrate_adapter.py`
  drives `SubstrateLoop.run_step` per `PlannedStep` from a `Harness.run`
  branch gated on `substrate_loop: true` in `ract.yaml`. Legacy
  `Executor.execute` path preserved for non-git workspaces.

### Added (anti-lazy)

- **Held-out suite (G1) + Mutation-kill (G2) (module_01, ADR-0019).**
  `DualAcceptanceSuite` + AES-GCM-sealed held-out predicates in
  `src/ract/antilazy/holdout.py`. `enforce_g1` / `enforce_g2` pre-commit
  helpers. `MutmutSource` stub. `evals/antilazy/G1-G2/` fixtures. New
  event kind `laziness.violated`. New config: per-intent G2 threshold,
  trivial-rate ceiling (0.3 over last 20 compositions) in module_04.
- **Patch differentiation (G3) + Coverage delta (G4) (module_02, ADR-0020).**
  `src/ract/antilazy/patchdiff.py` (companion-generated differentiator
  suite + AST-normalized leakage fingerprint + `--grep-marker` scan +
  retrieval-index secondary query). `coverage.py` (per-touched-file delta,
  three-run flakiness sample). `enforce_g3` / `enforce_g4` pre-commit
  helpers. `evals/antilazy/G3-G4/` fixtures (null_patch, solution_leakage,
  coverage_stagnation).
- **Test integrity (G5) + Symbol-graph under-edit (G6) (module_03, ADR-0021).**
  `src/ract/antilazy/testintegrity.py` — AST diff analyzer denying
  `pytest.skip`, `xfail`, `mark.skip*`, `mark.xfail`, assertion-removal,
  `assert True`, denied-file-edit, monkey-patch, and metaprogramming-escape
  shapes (including `importlib.import_module` and
  `type().__getattribute__`). `symgraph.py` — stdlib-ast symbol graph
  with SQLite snapshot-digest cache; `symgraph.db` + `.gitattributes`
  linguist-generated exclusion; `UnderEditReport`. Capability manifest
  extended with a `test_integrity` section (ALM §3.5 defaults;
  `ManifestValidator` refuses narrowed `denied_ast_patterns` /
  `denied_file_edits`). `enforce_g5` / `enforce_g6` pre-commit helpers
  emit `laziness.violated` with `kind=test_hack_denied` /
  `under_edit_uncovered_callers`.
- **Companion provider (G7) + Effort reconciliation (G8) (module_04,
  ADR-0022).** `src/ract/antilazy/companion.py` (`CompanionConfig` +
  `CompanionRedTeamReport` + `run_companion` + `enforce_different_provider`
  + `CompanionProviderCollisionError`). `effort.py` (`EffortEstimate` +
  `EffortActual` + `EffortReconciliation` — deterministic static
  heuristic with keyword-packing defense + small-fix suppressor +
  greenfield fallback). `completion_gate.py` (`CompanionBundle` +
  `CompletionGateOutcome` + `run_completion_gates`). `LoopController`
  accepts `companion` + `effort_estimate` kwargs; T1 done-callback runs
  completion gates. `evals/conformance/anti_lazy/` (10 fixtures);
  `_score_anti_lazy` scorer; `check_provider_gate anti_lazy_conformance`
  threshold (default 0.7). `evals/conformance/COMPANION_MATRIX.md` +
  `evals/leaderboard/update_companion_matrix.py` (idempotent regenerator).
- **Sycophancy circuit + Investigator + three-signature Rootknot +
  Invariant AL-1 (module_05, ADR-0023) — SACRED-SPINE CHANGE.** Rootknot
  schema bumped to `sidecar/v3` adding `antilazy_signature`,
  `gate_results` (tuple of eight `GateResult`), and `reversal_taint`
  (`"clean" | "partial"`). `AlmVerifierKey` in
  `src/ract/security/alm_verifier_key.py`. `Rootknot.attest_antilazy` /
  `verify_antilazy` / `make_rootknot_v3` triple-attester. `verify_workspace`
  extended with **Invariant AL-1 (Anti-Lazy Attestation)** three
  sub-clauses (AL-1.1 signature verifies; AL-1.2 every `GateResult` PASS
  or approved handshake; AL-1.3 `reversal_taint` clean or on operator's
  `accepted_partial_taint_runs` set). `sycophancy.py` (deterministic
  regex + heuristic classifier; `scan_trace` five-turn window;
  `force_evidence_or_restore` via `_RepairIntentSink` Protocol; emits
  `reversal.suspicious` event). `investigator.py` (`InvestigatorReport` +
  `InvestigatorFinding`; top-20 file selection by symbol-graph adjacency
  with lexicographic-earliest padding; emits `investigator.report` and
  `laziness.violated` `kind=investigator_missing`). Two new event kinds:
  `reversal.suspicious`, `investigator.report`.
- **Isomorphic perturbation gate for rule-like intents (module_06,
  ADR-0024).** `src/ract/antilazy/iso_perturb.py` (`RuleLikeDetection`
  with confidence score + word-boundary matched detector;
  `IsomorphicTransformation`; `transform_intent` producing
  `rename_entities` / `swap_syntax` / `permute_examples`;
  `compare_solutions` with AST-normalized digest + reverse-rename +
  string-similarity fallback; `run_iso_perturbation` orchestrator).
  `IntentCompiler.compile_and_detect_rule_like` extension surfacing
  `(suite, rule_like)`. `LoopController.iso_perturb` kwarg. New
  `iso_perturb.json` report per run; new advisory event kinds
  `iso_perturb_rename_degenerate` and `iso_perturb_producer_error`.
- **Anti-Lazy eval corpus + attested pass rate + companion matrix (module_07,
  ADR-0025).** `evals/antilazy/` corpus with 10 adversarial cases drawn
  from documented public incidents (OpenAI SWE-bench Verified audit,
  Palisade chess-hacking, METR reward-hacking taxonomy, Anthropic
  sycophancy research, iso-perturbation spec). `evals/leaderboard/update.py`
  extended with `claimed_pass_rate` + `attested_pass_rate` +
  `attestation_gap` columns; runs with no rootknot file EXCLUDED from
  both numerator and denominator. FakeProvider caveat marker on the
  leaderboard row. New CI workflow `evals-smoke.yml` (PR-tier 7-fixture
  smoke) alongside the nightly `evals-full.yml`.

### Changed

- **`signature` renamed to `generator_signature` on `Rootknot`** (substrate
  module_06). Deprecated `@property` alias emits `DeprecationWarning`
  and is removed in v0.5.
- **`--yolo` semantics changed** (substrate module_03) from "bypass
  handshake" to "auto-widen within pre-declared bounds" gated on
  `HandshakeRegistry.widen_manifest_for`. Tier 3 stays denied at a
  compile-time constant.
- **T1 termination rewritten** (substrate module_01) from milestone
  oracle to a predicate check reading the final snapshot. The old
  `ProgressOracle` becomes a scheduling heuristic only.
- **Rootknot schema bumped to `sidecar/v3`** (ALM module_05) adding
  `antilazy_signature`, `gate_results`, `reversal_taint`. `sidecar/v1`
  and `sidecar/v2` continue to verify at the non-strict floor; `strict=True`
  refuses v1 and v2 outright.
- **`__root_author__` moved to display-only** (substrate module_06) in
  `src/ract/_about.py`, read only by `ract --about`. Audit grep gate
  enforced by `tests/test_root_author_display_only.py`.
- **`evals/LEADERBOARD.md` FakeProvider display marker** (ALM module_07)
  — `` `fake` `` renders as `` `fake` (synthetic, mechanism-check only) ``
  in the provider column.

### Deprecated

- **`Rootknot.signature` property alias** — emits `DeprecationWarning`;
  removed in v0.5. Consumers migrate to `Rootknot.generator_signature`.
- **`sidecar/v1` and `sidecar/v2`** — continue to verify at the non-strict
  floor but skip RK-3 (v1) and AL-1 (v1 + v2) with
  `DeprecationWarning`. `strict=True` refuses them. Re-sign under
  v0.4-ALM to lift the bar.

### Removed

- Unused experimental modules and CLI subcommands from earlier
  development that were not part of the v0.4 substrate design. Users of
  the shipped v0.4 CLI verbs are unaffected.

### Verify

- **`v0.4.0-rc1` naming convention.** Substrate pipeline's plan referred
  to a `v0.4.0` tag, but substrate module_08 deferred the entire release
  surface (CHANGELOG, README, VERSION, ROADMAP, tag) to this pipeline.
  ALM's module_08 lands the FIRST v0.4-family tag as `v0.4.0-rc1` — the
  `rc1` suffix reflects that ALM code is new and the combined shape
  warrants a candidate cycle before `v0.4.0`. VERSION carries the
  human-friendly `v0.4.0-rc1`; `pyproject.toml` and `__init__.py` carry
  the PEP 440 canonical `0.4.0rc1`; `ract --version` prints `RACT
  0.4.0rc1` (PEP 440 normalises `0.4.0-rc1` and `0.4.0rc1` to the same
  version identity — see `tests/test_release_surface.py`
  `test_version_matches_across_files` and
  `test_ract_version_cli_reports_aligned_identity`). The tag itself
  uses the `v0.4.0-rc1` git convention.
- **46-signal sweep (documented total).** The plan called for a combined
  46-signal sweep (14 REBUILD + 16 SUBSTRATE + 16 ALM). Honest
  enumeration of the three specs finds 11 REBUILD signals (per
  `docs/RACT_v0.3_REBUILD_SPEC.md` §4) + 16 SUBSTRATE + 16 ALM = **43
  distinct signals**. `tests/test_release_surface.py` enumerates and
  evaluates all 43; the test formerly named `test_combined_signal_count_46`
  is renamed `test_combined_signal_count_matches_documented_total` and
  asserts 43.
- **New invariants.** RK-1 (Author Attestation, v0.2), RK-2 (Sidecar
  Integrity, v0.2), RK-3 (Environmental Attestation, this release), AL-1
  (Anti-Lazy Attestation, this release).
- **New CLI verbs (substrate).** `ract session ls`,
  `ract session diff <step_id>`, `ract conformance run --provider <name>`,
  `ract trace replay|fork|diff|to-test`.
- **New CLI verbs (ALM).** Anti-lazy gates are pre-commit helpers rather
  than top-level CLI verbs; a run's `evals/runs/<run_id>/` gains
  `mutation_kill.json`, `patch_diff.json`, `coverage_delta.json`,
  `test_integrity.json`, `under_edit.json`, `companion_report.json`,
  `effort_reconciliation.json`, `sycophancy.json`, `investigator.json`,
  and (for rule-like intents) `iso_perturb.json`.
- **New config options.** `substrate_loop: true` in `ract.yaml` (substrate
  module_08); `anti_lazy_conformance` threshold in
  `check_provider_gate` (default 0.7, ALM module_04); `AuctionConfig`
  block; `test_integrity` section in `CapabilityManifest`.
- **Retag addendum (2026-07-27, refreshed 2026-08-17).** The
  `v0.4.0-rc1` tag was first cut on commit `1fd764d` (2026-07-26). Two
  audit sweeps have force-moved the tag since:
  1. **2026-07-27 retroactive endpoints audit** landed two initial
     release-surface fix commits, moving the tag to `8b0a6c5`:
     - `0c853a9` audit(v0.4.0-rc1): fix — remove operator-project name
       from shipped docs.
     - `8b0a6c5` audit(v0.4.0-rc1): fix — substrate adapter rebinds
       every captured helper (enumerated `_HELPER_ATTRS` set plus
       regression test).
  2. **2026-07-27 through 2026-08-17 content-hygiene + functionality
     audits** landed nine more `audit(v0.4.0-rc1)` fix commits and the
     tag rests today at `dafab9a`. The eleven audit commits past the
     initial `1fd764d` tag position, in chronological order:
     `0c853a9`, `8f8b03f`, `c88ddc9`, `224fd90`, `0eed92d`, `2a11bef`,
     `17a4794`, `2fb5715`, `9b63094`, `3577149`, `dafab9a`. Version
     identity, 43-signal count, and every other release-surface claim
     are unchanged.

### Known limitations (carried to the v0.5 hardening backlog)

- Live-model reruns for the ALM `evals/runs/*_antilazy/` reports are
  FakeProvider mechanism-checks; the informative attested-vs-claimed
  delta requires live providers (queued as the nightly
  `evals-full.yml` workflow gated on `RACT_EVAL_ENABLED`).
- Reviewer-drift across the ALM pipeline: four of eight ALM modules'
  Second Pass reviewers fell back from the plan-named endpoint (see
  `docs/ROADMAP.md` "Operator-side dispatcher gaps").
- Full v0.5 backlog compiled from every module's Flagged gaps and every
  Second Pass deferral: see `docs/ROADMAP.md`.

## [0.3.0] - 2026-07-25 — Auditability and Depth

### Added

- **Public provenance statement** — `docs/PROVENANCE.md` is the single public document describing what a Rootknot attests, how RACT stays independent of private systems, how to verify a Rootknot, and what happens on violation (T3 `PROVENANCE_FAILURE`).
- **Independence lint** — `tests/test_public_provenance.py` AST-scans `src/ract/` and fails the build if any module imports from a root not in the curated allowlist. Adding a third-party dependency is now a conscious, reviewed act.
- **Failure-mode architecture** — `docs/ARCHITECTURE.md` gained a "Failure modes and concurrency" section; every named failure maps to a real `TerminationCause` or the `authorize_action` gate.
- **Two new ADRs** — [ADR-0008](docs/ADRs/ADR-0008-ract-yaml-versioning.md) (`ract.yaml` schema versioning) and [ADR-0009](docs/ADRs/ADR-0009-mcp-tool-execution-boundaries.md) (MCP/tool-execution boundaries), each with rejected alternatives. The repo now carries 9 ADRs.
- **Benchmark harness** — `evals/benchmarks/refactor-token-usage/` compares the milestone-driven loop against a naive fixed-iteration baseline on tokens-to-pass, with a committed `report.md` and a CI `benchmark` job. The contender is strictly better (80% fewer tokens on the refactor task).
- **Rootknot ergonomics** — `SessionKey.rotate()` archives the old key (pre-rotation rootknots still verify); `ract provenance verify <path>` CLI verb prints `valid`/`invalid`; the executor optionally signs and indexes every artifact write (SQLite + sidecar) when configured.
- **Repo hygiene** — `tests/fixtures/` convention with a hygiene lint test (no tracked root JSON, runtime dirs gitignored); CONTRIBUTING documents branch-protection requirements and repository conventions.

### Changed

- README trimmed to under 500 words; every public claim now references a command or a committed report. Added a "Verify" section.
- CI runs `ruff` over `evals/` and adds the `benchmark` job with report artifact upload.

### Removed

- The `_ROOT_KNOT = object()` sentinel deprecation note is retired — the sentinel is fully gone from `src/` and `tests/` (verified by grep).

### Known limitations (carried to the hardening backlog)

- `ract.yaml` schema-version enforcement (ADR-0008) is documented but not yet implemented in `config.py`.
- The benchmark proves the termination mechanism on one deterministic task; a multi-task sweep with varied pass-iteration profiles is queued.
- `ract provenance verify` resolves the generator public key from the local key store (the sidecar stores the key *id*, not the raw pubkey); embedding the raw pubkey in the sidecar is queued.
- Branch protection is documented; applying the GitHub settings is an operator action.

## [0.2.0] - 2026-07-23 — Provenance and Invariants

### Added

- **Signed Rootknot provenance** — every artifact carries an ed25519-signed `Rootknot` binding it to its plan step, assumption, generator, and parent artifacts. See [ADR-0001](docs/ADRs/ADR-0001-provenance-anchored-artifacts.md).
- **Provenance workspace verifier** — `verify_workspace` checks invariants RK-1 and RK-2 before every recursion step. See `src/ract/core/provenance.py`.
- **Assumption registry** — four-state lifecycle (`proposed`, `active`, `discharged`, `violated`) with transitive violation propagation. See [ADR-0002](docs/ADRs/ADR-0002-assumption-registry.md).
- **Formal loop termination** — recursion halts on T1–T7 with a distinct `TerminationCause`. See [ADR-0003](docs/ADRs/ADR-0003-milestone-driven-recursion.md).
- **Threat model** — capability tiers T0–T3, sandbox gating, and a published refuse-list. See [ADR-0004](docs/ADRs/ADR-0004-tool-execution-threat-model.md) and [ADR-0007](docs/ADRs/ADR-0007-what-ract-refuses.md).
- **Capability-based provider routing** — router selects providers by capability hint and health. See [ADR-0005](docs/ADRs/ADR-0005-provider-capability-routing.md).
- **Deferred-approval handshakes** — high-risk actions queue for async operator review. See [ADR-0006](docs/ADRs/ADR-0006-deferred-approval-handshakes.md).
- **Versioned plan schema** — `src/ract/core/schemas/plan-v1.json` with migration support.
- **Eval harness** — three reproducible tasks under `evals/tasks/` with committed run reports in `evals/runs/`.

### Changed

- README rewritten to a concise, technical pitch; author content moved to `AUTHOR.md`.
- CI badge and coverage badge added to README.

### Deprecated

- The `_ROOT_KNOT = object()` sentinel is retained as a legacy fallback through v0.2.0 and will be removed in v0.3.0.

## 0.1.2

### Added

- **Signed receipts and receipt chain**: every run produces a signed receipt; receipts can be chained tamper-evidently and exported.
- **Handshake queue**: operator handshakes queue high-risk items for async review.
- **Dead-code auction**: `ract auction list` identifies unreachable modules; `ract auction html-report` exports HTML reports.
- **AI provenance manifest / SBOM**: `ract ai-sbom` and `ract manifest` build and export AI provenance manifests.
- **Configurable CI policy gate**: `ract policy-gate` evaluates JSON policies against run evidence.
- **Coverage delta**: `ract coverage delta|baseline|status|badge` implements earned-coverage gates.
- **Mutation merge gate**: `ract merge-gate` evaluates natural-language merge policies against mutation metrics.
- **Native internal provider**: route prompts to local scripts via `adapter: internal`.
- **MCP adapter health probe**: verify MCP tool wiring before running loops.
- **Receipt leaderboard**: `ract leaderboard` renders model/plan ranking tables from receipts.
- **Deterministic run fingerprints**: `ract run-fingerprint` fingerprints runs for reproducibility studies.
- **Run report exports**: Markdown, HTML, and JSON run reports for CI artifacts.
- **Quality scorecard JSON export**: archive and compare quality scorecards across runs.
- **Novelty scan fast mode**: `ract novelty scan --fast` finishes in seconds for CI.
- **New CLI verbs**:
  - `ract --version`
  - `ract config validate`
  - `ract provider health`
  - `ract session list`
  - `ract plan diff`
  - `ract init --list-templates`
  - `ract doctor --json`
- **JSON output flags** across the CLI surface:
  - `ract retrieval search --json`
  - `ract diff apply --json`
  - `ract skills list --json` and `ract skills marketplace list --json`
  - `ract mcp list --json`
  - `ract run-fingerprint --json`
  - `ract leaderboard --json`
  - `ract mutation run --json`
  - `ract refactor --dry-run --json`
  - `ract whisper --json`
- **Diff applier context verification**: `ract diff apply` now validates hunk context before writing and parses both git-style and plain unified-diff headers.

### Changed

- Thermal governance in the build loop now uses a hard ceiling and a separate concurrency-fallback threshold.
- Provider router now registers the `internal` adapter by default.

## 0.1.1

- Trust and tooling release: dead-code auction, Chesterton's Fence, consolidation, rot report, and provider routing.

## 0.1.0

- Initial public release of RACT.
