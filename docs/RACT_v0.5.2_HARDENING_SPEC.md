# RACT v0.5.2 Hardening Spec

**Ships as:** v0.5.2 (patch bump; substrate + sandbox + subagent + trace + run_id hardening)
**Owner:** Release pipeline author
**Authored:** 2026-08-22
**Trigger:** Deep-audit A (Rootknot v4 + substrate) + Deep-audit B (runtime + trace + memory) — 2026-08-22 Ox Alpha-partnered adversarial passes at `_BUILD/audit_2026-08-22b/DA_{A,B}_*.md`
**Base tag:** v0.5.1 at `300f8b22` (spec-completeness round-2, awaits push)

## 1. Purpose

Close the HIGH-severity findings surfaced by the DA-A + DA-B adversarial audits. Every finding was Ox-Alpha-verified against my initial pass; Ox Alpha ADDED 7 findings I missed originally (5 in DA-B, 2 in DA-A). Ships as v0.5.2 patch — no breaking changes; sacred spine unchanged; adds hardening at defense-in-depth layers where audits found attackable/lossy behavior.

## 2. Non-goals

- No new features (all v0.6+ scope per ADR-0043/44/45/46 remains deferred).
- No Kairos references (post-filter-repo state preserved).
- No breaking Rootknot 3-signature schema. Enforce EXISTING schema invariants more strictly — do not add new fields.

## 3. Sacred spine — invariants preserved (and strengthened)

- Rootknot 3-signature schema unchanged, but v4 schema-label now STRUCTURALLY implies v4 fields present + non-empty (module_01 fix; closes v4-label-attack surface).
- Author-name-free tree.
- Closed-IP wordlist zero-tolerance (zero kairos anywhere).
- AL-1 property (structural per wiring module_07).
- Handshake-always for push.

## 4. Discipline — 13-step build flow per operator directive 2026-08-22

Every module executes the full 13-step flow documented at `_BUILD/ract_v0.5.2_hardening/SESSION_PLAN_2026-08-22.md` §"Expanded module discipline":

1. Spec (this doc)
2. PRE Depth Chain
3. PRE Lateral Chain
4. **Intent grounding** — cite spec § + operator vision doc
5. **Architecture grounding** — cite ARCHITECTURE.md + subsystem context
6. **Co-build with Ox Alpha** — dispatch Ox Alpha DURING build for design forks
7. Build
8. POST-pre Depth Chain
9. POST-pre Lateral Chain
10. Audit (Ox Alpha primary + cross-family reviewer)
11. POST-post Depth + Lateral
12. BUILD-what-emerged
13. **UX grounding** — cite user-visible impact + doc update

Every fragment carries all 13 steps + role solicitations (per RACT v0.6 concept doc). Every commit body names intent/arch/ux refs + roles.

## 5. Module map (6 modules; module_06 is release close)

### module_01 — Rootknot v4 signature hardening (5 audit findings closed)

Closes: **DA-A F-1 + F-2 + F-5 + M-1 + M-2** (systemic Rootknot v4 attack surface).

**Findings** (verbatim from DA-A):
- Rootknot dataclass allows `schema_version=4, workspace_digest=None, prompt_digest=None, run_id=""` direct construction
- `canonical_bytes()` at `rootknot.py:262-267` emits v4 fields only when truthy — attacker with SessionKey mints v4-labeled attestation binding nothing
- Sidecar reader at `provenance.py:492` accepts absent via `data.get("run_id", "")`
- Verifier `_check_rk3` / `_classify_violation` at `provenance.py:683-956` never asserts v4-label implies v4-fields
- **Ox Alpha M-1:** verifier has no `min_acceptable_schema_version` policy → v4 → relabel v1 → re-sign accepts weaker attestation (DOWNGRADE attack)
- **Ox Alpha M-2:** `if knot.schema_version < 3` accepts unknown v9 with drifted semantics (forward-compat drift)

**Fix:**
- Add `Rootknot.__post_init__` validation: `schema_version == 4` requires `workspace_digest` non-None + `prompt_digest` non-None + `run_id` non-empty. Raise `RootknotSchemaViolation`.
- Add verifier v4-branch check: `_check_rk3` asserts v4-labeled payload has all v4 fields; refuses otherwise.
- Add `min_acceptable_schema_version` policy: verifier configurable min; default = 3 (accepts v3+); operator can set to 4 for strict.
- Add `known_schema_versions` allowlist `{1, 2, 3, 4}` — unknown v9 rejects rather than treats as v1.
- Property test: `sign_v4(None-field)` → verify FAILS; `sign_v4_relabel_as_v1` → verify FAILS with DOWNGRADE reason; `verify(v9)` → verify FAILS with UNKNOWN_SCHEMA reason.

**Grounding:** Intent = sacred spine 3-signature schema is real, not decorative. Architecture = `rootknot.py` + `provenance.py`. UX = no user-visible unless operator explicitly rejects v4-labeled attack payload (WARN + audit-log entry).

### module_02 — Sandbox env allowlist library-injection defense (3 audit findings)

Closes: **DA-A F-3 + M-3 + M-4**.

**Findings:**
- `sandbox_env.py:123-169` NEVER_PASSTHROUGH misses classic library-injection vectors
- **Ox Alpha M-3:** repo-controlled `.ract/sandbox_env.allowlist` trust-tier design flaw
- **Ox Alpha M-4:** Windows case-insensitivity gap in allowlist union keying (`sandbox_env.py:422`)

**Fix:**
- Extend `NEVER_PASSTHROUGH` with 30+ library-injection env vars: `LD_PRELOAD`, `LD_LIBRARY_PATH`, `LD_AUDIT`, `DYLD_INSERT_LIBRARIES`, `DYLD_LIBRARY_PATH`, `DYLD_FRAMEWORK_PATH`, `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, `PYTHONUSERBASE`, `NODE_OPTIONS`, `NODE_PATH`, `BASH_ENV`, `ENV`, `PERL5OPT`, `PERL5LIB`, `RUBYOPT`, `RUBYLIB`, `JAVA_TOOL_OPTIONS`, `JAVA_OPTS`, `GLIBC_TUNABLES` (CVE-2023-4911), `LOCPATH`, `NLSPATH`, `GIT_SSH_COMMAND`, `GIT_EXEC_PATH`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_GLOBAL`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `CARGO_HOME`, `GOPATH`, `RUSTFLAGS`, `MAKEFLAGS`, `PSMODULEPATH`.
- Trust-tier for `.ract/sandbox_env.allowlist`: file must be operator-signed (Rootknot v4 attestation) OR refuse with clear error. Repo-committed allowlist file no longer trusted by default.
- Windows case-insensitive keying: allowlist union normalizes env var names to upper-case on Windows only.
- Regression: seed process env with each new library-injection var; assert absent from sandbox env on Linux + macOS + Windows-stub.

**Grounding:** Intent = sandbox is defense-in-depth against a compromised model. Architecture = `sandbox_env.py`. UX = no user-visible unless legit build system uses one of the newly-denied vars (WARN + count-only log).

### module_03 — Subagent lifecycle + PID-reuse hardening (2 audit findings)

Closes: **DA-A F-4 + M-5**.

**Findings:**
- `SubprocessSubagentHandle.dispose` at `subagent_handle.py:174-176` short-circuits + latches `_disposed=True` when parent Popen exited — skips `kill_tree` → grandchildren survive
- Docstring at line 178-181 promises "grandchild caught structurally" — the exact invariant broken by short-circuit
- **Ox Alpha M-5:** PID-reuse hazard on subsequent `kill_tree` — need `(pid, creation_time)` capture; killing wrong process if PID reused between spawn + kill

**Fix:**
- `SubprocessSubagentHandle.__init__` captures `(pid, creation_time_ns)` tuple via `psutil.Process(pid).create_time()` (or Windows `GetProcessTimes` equivalent). Store on handle.
- `dispose` no longer short-circuits on parent-exited — ALWAYS calls `kill_tree(handle)` which uses `(pid, creation_time)` to verify identity before signal.
- `kill_tree` checks: for each child pid, `psutil.Process(pid).create_time() > handle.parent_create_time` (child spawned after parent; excludes reused PIDs).
- Docstring updated to reflect actual behavior.
- Regression: mock Popen.poll() to return non-None (parent exited); call dispose; assert kill_tree still fires. Also: mock a reused PID scenario; assert kill_tree skips the reused one.

**Grounding:** Intent = subagent cascade on halt is a load-bearing invariant. Architecture = `subagent_handle.py` + `process_group.py`. UX = no user-visible unless operator observes reap latency change (log entry).

### module_04 — Run_id continuity: sidecar schema + subprocess plumbing (2 audit findings)

Closes: **DA-B F-3.1 + F-3.2**.

**Findings:**
- `spawn_step_subprocess` (executor/loop.py:585-638) never plumbs `RACT_RUN_ID`; ContextVar can't cross process boundary; child `JsonlEventWriter()` raises
- Loop-state sidecar (loop_controller.py:1316-1327) lacks `schema_version` + `run_id` binding; `repair_attempts_remaining` rename silently restores default budget (unbounded loop); no run-binding → cross-run resume bleed

**Fix:**
- `spawn_step_subprocess` env kwarg auto-adds `RACT_RUN_ID={ambient_run_id}` when ambient set; child process reads env at boot + rebinds ContextVar.
- Loop-state sidecar gains `schema_version: 1` + `run_id: str` top-level fields. `on_resume` validates schema_version + run_id match current run; refuses otherwise.
- Rename field `repair_attempts_remaining` → `repair_attempts_remaining_v1` (or bump schema_version) so silent-restore on rename becomes impossible.
- Regression: `subprocess` spawned inside a run with ambient run_id → child's `RACT_RUN_ID` env matches. `on_resume` with mismatched run_id → refuses.

**Grounding:** Intent = run_id preservation is a Pipeline A' module_06 core invariant. Architecture = `executor/loop.py` + `loop_controller.py`. UX = trace consistency (no user-visible unless operator inspects mid-run events + sees ambient bind).

### module_05 — Trace log durability + honest verify (5 audit findings)

Closes: **DA-B F-4.1 + F-4.2 + F-4.4 + F-4.5 + F-4.6**.

**Findings:**
- F-4.1 `iter_events` + `_reseed_tip_from_disk` read whole file → O(N²) on per-open reseed × per-step reopen
- F-4.2 `verify_chain` bool-return conflates "intact" with "anchored"; no external anchor
- F-4.4 Out-of-lock observers → delivery-order inversion between concurrent emitters + external tailer
- **Ox Alpha F-4.5:** Strict UTF-8 decode of possibly-torn tail (writer.py:281-288, :614) → post-crash log unreadable
- **Ox Alpha F-4.6:** `raw.split("\n")` mishandles CRLF from Windows-authored / edited logs

**Fix:**
- `_reseed_tip_from_disk`: incremental — cache last-known-fpos + tip_hash; on reopen, seek to cached fpos + read forward. O(events-since-last-seed) not O(N).
- `iter_events`: streaming generator; yields per-line; caller iterates. Not `readlines()`.
- `verify_chain` returns `LedgerVerifyResult(valid: bool, unanchored_prefix_entries: int, expected_count: int|None, first_break_at: int|None)`. Bool remains for backward-compat via `.valid`.
- Observer ordering: use `queue.Queue` per-observer serial dispatch; per-observer ordering preserved even under concurrent emit.
- Torn-tail UTF-8: last-line decode uses `errors="replace"` — post-crash tail readable + repair() can still process. Body-line UTF-8 stays strict.
- CRLF handling: `raw.splitlines(keepends=False)` instead of `raw.split("\n")` — handles CRLF/LF/CR uniformly.
- Regression: 100k-event log reseed benchmark (<100ms); torn-tail simulation with invalid UTF-8; CRLF-authored log parses cleanly.

**Grounding:** Intent = trace log survives crash + supports post-hoc forensics. Architecture = `writer.py` + `manifest_ledger.py`. UX = `ract trace repair` outputs readable stream on crash tail; `ract manifest ledger verify` outputs distinguishes intact vs anchored.

### module_06 — Memory system polish + docs + release close (2 audit findings + close)

Closes: **DA-B F-5.1 + F-5.4** + release-close discipline.

**Findings:**
- F-5.1 Dataclass regex over-permissive (`@my.dc` matches); doc/behavior mismatch
- **Ox Alpha F-5.4:** Network-share `on_moved` src/dest reordering → stale cache-miss window

**Fix + close:**
- Dataclass regex tightened to only match `@dataclass`, `@dc`, `@dataclasses.dataclass` (whitelist rather than permissive).
- `on_moved` handler: use file-content hash to disambiguate src vs dest on network-share reorder.
- CHANGELOG `[0.5.2]` section authored with per-module bullets + audit-finding cross-refs.
- Golden hash re-locked.
- Full pytest suite green (target: 3150+ pass with 0 failures — the 3 pre-existing failures were closed in `1043a4b`).
- Ox Alpha + cross-family re-audit at `_BUILD/audit_2026-08-22c/` — verify all 15+13 findings from DA-A + DA-B are CLOSED or explicitly ADR-deferred with reason.
- Version bump: `0.5.1` → `0.5.2` in VERSION + pyproject.toml + src/ract/__init__.py.
- Annotated tag `v0.5.2` (body ≤ 500 chars).
- Backup existing v0.5.1 tag as `backup-v0.5.1-preHardening`.
- HANDSHAKE_PUSH_COMMANDS.md at `_BUILD/ract_v0.5.2_hardening/`. **NO PUSH.** Operator gates.

**Grounding:** Intent = memory cache honesty. Architecture = `grouping.py` + `symbol_watcher.py`. UX = no user-visible unless operator observes cache-hit ratio.

## 6. Gate matrix

| Gate | Enforcer | Module |
|---|---|---|
| Rootknot v4 __post_init__ rejects None fields | `test_rootknot_v4_post_init_validation.py` | 01 |
| Verifier rejects v4 relabel-as-v1 DOWNGRADE | `test_rootknot_downgrade_defense.py` | 01 |
| Verifier rejects unknown schema_version | `test_rootknot_forward_compat_reject.py` | 01 |
| Sandbox env strips 30+ library-injection vars | `test_sandbox_env_library_injection_defense.py` | 02 |
| Repo-committed allowlist file untrusted | `test_sandbox_allowlist_trust_tier.py` | 02 |
| Windows case-insensitive allowlist keying | `test_sandbox_env_windows_case_insensitive.py` | 02 |
| dispose reaps grandchildren even when Popen exited | extend `test_subagent_cascade_forced_failure.py` | 03 |
| kill_tree PID-reuse guard | `test_kill_tree_pid_reuse_guard.py` | 03 |
| Subprocess ambient run_id plumbed | `test_spawn_step_subprocess_run_id_env.py` | 04 |
| Loop-state sidecar schema_version + run_id | `test_loop_state_sidecar_schema.py` | 04 |
| Torn-tail UTF-8 readable | `test_writer_torn_tail_utf8_replace.py` | 05 |
| verify_chain LedgerVerifyResult shape | `test_manifest_ledger_verify_shape.py` | 05 |
| Incremental reseed <100ms on 100k events | `test_writer_incremental_reseed_perf.py` | 05 |
| Dataclass regex whitelist | `test_grouping_dataclass_regex_whitelist.py` | 06 |
| on_moved network-share disambig | `test_symbol_watcher_on_moved_network_share.py` | 06 |
| Golden hash re-locked | `test_source_digest.py` | 06 |
| Full pytest suite green | full pytest | 06 |

## 7. Rollback protocol

Each module lands as one commit. `git revert <sha>` in reverse order. Sacred spine invariants preserved throughout (v4 hardening is additive at validation layer, not schema layer).

## 8. Handshake

Push happens ONLY after operator confirmation in chat. Pipeline writes HANDSHAKE_PUSH_COMMANDS.md at module_06 close; operator gates.

## 9. Ox Alpha co-build discipline

Every module dispatches Ox Alpha at step 6 (co-build) for design forks BEFORE code lands, in addition to step 10 (SP audit) after code lands. Ox Alpha's session-1 win rate over the cross-family reviewer on rigor (module_05 SP: 3 Q3 DEFECTS Ox flagged that the cross-family reviewer missed; DA-A + DA-B: 7 findings Ox added that main-agent missed) justifies this asymmetric deployment.
