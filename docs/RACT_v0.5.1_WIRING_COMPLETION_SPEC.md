# RACT v0.5.1 Wiring Completion Spec

**Ships as:** v0.5.1 (re-tag; drops current `bb8e013`-tagged version in favor of a wired v0.5.1)
**Owner:** Release pipeline author
**Authored:** 2026-08-21
**Trigger:** 8-lens deep audit (`_BUILD/audit_2026-08-21/AUDIT_SUMMARY.md`) surfaced the systemic wiring gap — v0.5.1's primitives shipped as clean-tested API surfaces with zero production callers.

## 1. Purpose

Close the SYSTEMIC WIRING GAP. Every module of Pipeline A' delivered a correct primitive; production runtime paths bypass all of them. This pipeline wires those primitives into the loop controller, tool dispatch, sandbox execution, event emission, and memory indexes — turning v0.5.1's promises into operational behavior.

**Threat closure verified:** G1 crash-consistency, G2 workspace binding, G3 prompt drift — all currently unclosed in production despite v0.5.1 tagging. This pipeline makes them actually closed.

## 2. Non-goals

- No new primitives (all needed pieces exist; only wiring is missing).
- No architectural refactor beyond what the audit findings require.
- No v0.6 feature work (deferred flagged gaps stay deferred).
- No Kairos reference of any kind (per hard-wall rule).

## 3. Sacred spine — invariants preserved

- Rootknot 3-signature schema unchanged (this pipeline wires the v4 factory into use, not schema changes).
- Author-name-free tree.
- Closed-IP wordlist zero-tolerance.
- AL-1 property.
- Handshake-always for push.

## 4. Module map

Each module: chain (PRE) → build → chain (POST-pre) → audit (SP) → chain (POST-post) → BUILD what emerged → close. One primary commit per module (revert-friendly). Amendment commits allowed for SP-surfaced fixes.

**Key SP addition for this pipeline:** every SP prompt must explicitly ask *"Is this primitive actually reached from the loop controller in production code paths? Show the call chain."* This is the gap the prior pipeline's SP discipline missed.

### module_01 — Provenance + docs sync (CHANGELOG SHA regen + THREAT_MODEL/PROVENANCE/EVENTS/ROADMAP)
Fixes:
- **Lens B C1:** regenerate CHANGELOG `[0.5.1]` bullet SHAs against current git log (all 20 pre-filter-repo SHAs invalid post-rewrite).
- **Lens B C2:** fix CHANGELOG self-contradiction on ADR count (2 exist, claims 10).
- **Lens B C3:** write ADR-0042 (sycophancy v2 tuning band) — promised in module_09 fragment, never delivered.
- **Lens B C4:** update `docs/THREAT_MODEL.md` — reflect module_05 substrate closures (env allowlist, tool gate, process-group kill, git compensator) + module_07 manifest ledger + JCS (not "canonical JSON sorted keys").
- **Lens B C5:** update `docs/PROVENANCE.md` — verify-by-hand recipe uses `dumps_jcs()`, sidecar schema table extends to `sidecar/v4`.
- **Lens B C6:** update `docs/EVENTS.md` — schema_version bump, 6 new EventKinds (`assumption.accepted`, `tool.invocation.pre|post|refused`, `manifest.ledger.appended|refused`, `whisperer.contract_violation`).
- **Lens B major:** ROADMAP absorb v0.5.1 flagged gaps roll-up.
- Docstring drift in `src/ract/core/rootknot.py:246,690` (still cites `json.dumps(sort_keys=True)`).

### module_02 — Rootknot v4 production wire-in
Fixes:
- **Lens D D2:** migrate production Rootknot creation from `make_rootknot` → `make_rootknot_v4`. Grep `src/ract/` for every `make_rootknot(` call; convert to v4 factory with `workspace_digest` + `prompt_digest` + `run_id` populated from ambient context.
- **Lens D D1:** fix `provenance.py` sidecar `_knot_to_json` — add v4 branch preserving all three new fields + `retrieval_attestation`. Round-trip test at unit level.
- **Lens D D3:** fix WAL replay regression under torn-pair — `_apply_wal_entry("proposed")` must NOT overwrite terminal states (DISCHARGED/VIOLATED).
- **Lens D D5:** fix Windows `msvcrt.locking` on `O_RDONLY` handles in `WorkspaceDigestChain.edges()` + `SuiteChain.entries()` — open with `O_RDWR` or degrade gracefully to lock-free read.
- **Lens D D4:** fix `intent_recompile` — pass actual `WorkspaceSnapshot(files=...)` not empty snapshot; T1 predicate set no longer silently stripped.

### module_03 — Tool gate chokepoint
Fix **Lens C C-01:** wire every tool invocation through `SubstrateLoop.invoke_tool()`. Sites to migrate:
- `src/ract/mcp_adapter` (grep for actual filename — MCP adapter file)
- `src/ract/providers/internal_provider.py`
- `src/ract/contracts/` — every tool caller
- `src/ract/executor/steps.py` — subprocess spawning path
- Any other `run_command` / `invoke_shell` / `execute_tool` sites

`invoke_tool` becomes THE single choke point. Add a property test: any tool invocation that does not route through the gate is a bug.

### module_04 — Enforced-sandbox env allowlist wire-in
Fix **Lens C C-02:** wire `NEVER_PASSTHROUGH` filter into:
- `src/ract/security/sandbox_linux.py:211-214` — currently reads `manifest.env.passthrough` without filter; must call `build_sandbox_env(...)` from `sandbox_env.py`.
- `src/ract/security/sandbox_macos.py` — currently zero env-scrub; wire same.
- Add `sandbox.env_scrubbed` event emission from all backends (Lens F L2).
- Regression: seed process env with fake `OPENAI_API_KEY` / `AWS_ACCESS_KEY_ID`; spawn each enforced backend; assert secrets absent from sandbox env.

### module_05 — Process-group tree-kill wire-in
Fix **Lens C C-03:** every subprocess spawn in `src/ract/executor/steps.py` (and any other spawn site) must use `process_group.spawn()`, and every rollback path must call `process_group.kill_tree()`. Grep for `subprocess.Popen(` / `subprocess.run(` / `os.spawn` across `src/ract/`; migrate each.

**Also:** fix **Lens C C-04** — `_fast_forward_head` in `loop.py:601` uses `git reset --hard` unconditionally; must use soft reset when the commit compensator is on the accumulator (preserves working-tree inspectability the compensator was designed for).

### module_06 — Ambient run_id wire-in
Fix **Lens G G-01:** wrap `loop_controller.py:1362`'s bare `ThreadPoolExecutor.submit(run_ract, ...)` with `run_with_ambient(run_ract, ...)`. This one-line fix reintroduces module_06's intended contract.

Also: **Lens G G-02** — replace hand-rolled run_id resolution at `loop_controller.py:1231` (iso-perturb gate) with `self._resolve_run_id(state)`.

Also: **Lens H C4** grep audit — every `ThreadPoolExecutor.submit` + `asyncio.gather` + `pool.submit` site in `src/ract/`; wrap with `run_with_ambient` or document explicit non-propagation.

Also: **Lens G G-04, G-05, G-03** — loop-resume path: persist `iterations`, `previous_score`, `stagnation_count`, `_rollback_streak`, `_prev_iteration_plan`, `_completed_families`, `repair_attempts_remaining`, `_repair_intent`, `last_known_good_workspace` across restart. Add `LoopController.on_pause`/`on_resume`/`resume()` methods. Compaction survival test that re-enters `run()` post-persist.

Also: **Lens G G-08** — iter-1 T8 tree-wipe protection: drift check must run AFTER snapshot init (move `check_t8` call from line 817 to after 838), and `delete_orphaned_files_on_t8=True` should require confirmation on iter-1.

### module_07 — Anti-lazy dispatch wire-in
Fix **Lens E AL-E-01:** wire `sycophancy_v2.classify` into the anti-lazy dispatch chain. Currently zero live callers. Locate where the legacy `sycophancy.py` detector fires; add v2 alongside (or replace) with fallthrough for parse failures.

Fix **Lens E AL-E-02:** wire polyglot G5/G6 shims (`enforce_g5_dead_code_polyglot`, `enforce_g6_test_copy_paste_polyglot`) into `loop_controller.py`. Replace Python-AST legacy path with polyglot dispatcher. `.ts`/`.rs`/`.go` patches actually get analyzed.

Fix **Lens E AL-E-03:** implement `enforce_g1`, `enforce_g7`, `enforce_g8` in `pre_commit.py` — currently missing. G7/G8 silently no-op when `final_diff is None`; must emit `laziness.violated` or `laziness.skipped` events.

Fix **Lens E AL-E-04:** promote AL-1 attestation from convention to invariant. Add `*GateOutcome` dataclass carrying `rootknot_signature` field; `core/loop.py:477` and `intent_recompile.py:363` currently accept `rootknot_signature=None` — reject or require.

### module_08 — Memory index watcher wire-in
Fix **Lens E MEM-E-01:** wire cache invalidation. `SymbolIndexWatcher` must hold a `RetrievalCache` handle and invalidate on index update. Add TTL enforcement (read `created_at`).

Fix **Lens E MEM-E-02:** extend `SymbolIndexWatcher` to also update `graph_index`, `semantic_index`, and `graph_populator` on source changes. Currently only `symbol_index` updates; 3 indexes drift silently.

Fix **Lens E MEM-E-03:** wire probe consumers. `read_capability_record` must be called from budget/cascade/persistence code paths — currently written but never read. Self-adjustment becomes live.

Fix **Lens E MEM-E-04:** wire `CompositionRunner` + `ProbeScheduler` into loop_controller for composed retrieval + periodic probe checks.

### module_09 — JCS migration completion + ledger integrity closures
Fix **Lens F H3:** migrate the 16 escaped `json.dumps(sort_keys=True)` hash-input sites to `dumps_jcs`. Notable sites: `plan_replay.py:122`, `memory/repo_fingerprint.py:325`, `memory/probes/scheduler.py:270`, every `antilazy/*.py` report canonical serialization, `predicate.py:374`. Tighten grep-gate to catch these.

Fix **Lens F H1:** `JsonlEventWriter.__init__` must replay on-disk tail to reconstruct `EventChain.tip_hash` before accepting new appends. Currently resets to `_GENESIS_HASH` on every construction, silently breaking chain.

Fix **Lens F H2:** align EventChain's tail-truncation behavior with other ledgers (WARN + tolerate, not hard-fail); OR align all ledgers to hard-fail (operator preference).

Fix **Lens F H4:** manifest-ledger `verify_chain` must detect middle-excise attacks. Add total-entry-count sidecar; verify count matches recomputed count during verify.

Fix **Lens G G-06:** replace `except Exception: pass` in `core/loop.py:479` chain-init with explicit error handling + logged failure.

### module_10 — UX + CLI cleanup + retrieval query + `.ract`/`.rack` unification
Fix **Lens A C1:** `ract --help` must show subverbs. Migrate to full argparse subparsers instead of `argv[0]` dispatch.

Fix **Lens A C2:** unify state directory. `.ract/` vs `.rack/` drift is load-bearing. Pick ONE (recommend `.ract/`), migrate every code path + doc + ADR, add a migration shim for existing installs.

Fix **Lens A C3:** wire `ract retrieval query` — currently prints "queued for v0.6" and exits; wire to actual `retrieve()` primitive from module_08.

Fix **Lens A M1:** add `ract manifest ledger` CLI verbs (`verify`, `inspect`, `show <entry-index>`, `proof <entry-index>`).

Fix **Lens A M3:** delete duplicate `marketplace` dispatch at `cli.py:4062-4063`.

Fix **Lens A M4:** `--auto` TTY guard — refuse `input()` calls in non-TTY sessions.

Fix **Lens A M7:** bare `ract retrieval` / `ract memory` / `ract plan` return exit 0 after printing help (not 1).

Fix **Lens A M8:** auto-generate verb index in README from actual CLI parser (single source of truth).

Fix **Lens A minor** — flag naming standardization, mutex groups, `required=True` on subparsers.

### module_11 — Release close + re-verification audit + re-tag
- Version stays `0.5.1` (re-tag, not bump).
- CHANGELOG `[0.5.1]` regenerated (SHA sync + accurate scope description; adds "wired: X, Y, Z" per module).
- Golden hash re-locked at new HEAD.
- Full pytest suite green (target: 2800+ pass with 0 failures).
- **Re-run 8-lens audit** — all 3 CRITICAL + 2 HIGH from Lens D, 3 CRITICAL from Lens C, 5 CRITICAL/HIGH from Lens E must be resolved. Audit summary file for this run at `_BUILD/audit_2026-08-21b/AUDIT_SUMMARY.md`.
- Delete `bb8e013` tag reference (rename `v0.5.1` → new SHA); backup old ref.
- HANDSHAKE_PUSH_COMMANDS.md rewritten at new commit.
- Operator gates push.

## 5. Gate matrix additions (over Pipeline A's)

| New gate | Enforcer | When |
|---|---|---|
| Every `make_rootknot(` in `src/` uses v4 factory | grep-gate test | module_02 |
| Every tool invocation routes through `invoke_tool` | property test | module_03 |
| Enforced sandbox strips NEVER_PASSTHROUGH env | integration test with seeded env | module_04 |
| Every `subprocess.Popen(` uses `process_group.spawn` | grep-gate test | module_05 |
| Every `ThreadPoolExecutor.submit(` uses `run_with_ambient` | grep-gate test | module_06 |
| polyglot G5/G6 fires on non-.py patches | integration test | module_07 |
| Memory 3-index consistency after source change | integration test | module_08 |
| Zero `json.dumps(sort_keys=True)` in canonical paths | grep-gate test (tightened) | module_09 |
| `ract --help` lists all subverbs | CLI snapshot test | module_10 |
| 8-lens re-audit produces zero critical wiring gaps | ad-hoc verification | module_11 |

## 6. Second-Pass discipline update

Every SP prompt this pipeline MUST include:
- Q: "Show the production call chain from a real entry point (CLI verb, loop controller, or user-facing API) to the primitive under review. If the primitive has no such call chain, the module has not shipped."
- Q: "What test asserts the wiring holds — not just the primitive's internal correctness?"

## 7. Rollback protocol

Each module lands as one commit. Revert = `git revert <commit>` in reverse module order.

## 8. Handshake

Re-tag `v0.5.1` happens in module_11. Push commands written to HANDSHAKE_PUSH_COMMANDS.md; operator gates.
