# RACT v0.6 backlog

Deferred carryover from the v0.5.2 hardening pipeline (modules 01–06)
and the two Deep Audit passes DA-A + DA-B (2026-08-22). Format per
Ox Alpha co-build Q3 verdict (2026-08-22): owner-column table with
inline expanded notes below the table for the highest-severity rows.
Anchor links inside the table point to the notes.

Each row names:

- **Item ID** — a stable slug (m0N-CX or DA-X F-Y for finding rows).
- **Discovered by** — the module (or audit lens) that surfaced it.
- **Severity** — HIGH / MED / LOW / INFO / PROCESS.
- **One-liner** — the shortest useful description.
- **Proposed owner** — the v0.6 module (or category) that should
  ship it.
- **Status** — reserved column, updated as items move through v0.6.

Add a **Status** column value once the item enters an active v0.6
module; do not mutate the discovered-by/severity columns retroactively.

## Backlog table

| Item ID | Discovered by | Severity | One-liner | Proposed owner | Status |
|---|---|---|---|---|---|
| [m02-M3](#m02-m3) | module_02 co-build | HIGH | `.ract/sandbox_env.allowlist` repo-trust-tier redesign (Rootknot v4 attestation) | v0.6 module_A `sandbox_env_trust_tier` | reserved |
| m02-C1 | module_02 co-build | MED | Sanitized-reinject for HOME/SHELL/PATH (don't just deny) | v0.6 module_A | reserved |
| m02-C2 | module_02 co-build | MED | Controlled-injection `trust_bundle` field | v0.6 module_A | reserved |
| m02-C3 | module_02 co-build | MED | Controlled-injection `egress_policy` field | v0.6 module_A | reserved |
| m02-C4 | module_02 co-build | LOW | Allowlist file JSONL homoglyph smuggle detector | v0.6 module_A | reserved |
| m03-C1 | module_03 | LOW | Windows 11 wmic→PowerShell fallback (wmic deprecated) | v0.6 module_B `process_identity_ps` | reserved |
| m03-C2 | module_03 | LOW | Linux 5.3+ `pidfd_open` upgrade path | v0.6 module_B | reserved |
| m03-C3 | module_03 | LOW | Cross-session pgid preservation on setsid drift | v0.6 module_B | reserved |
| m04-C1 | module_04 | MED | Sidecar writer sweep → `write_sidecar_header` universal | v0.6 module_C `sidecar_universal_sweep` | reserved |
| m04-C3 | module_04 co-build | LOW | Asymmetric partial-env detection (subset heuristic) | v0.6 module_C | reserved |
| [m04-C4](#m04-c4) | module_04 | LOW | `--strict-sidecar-headers` opt-in CLI flag | v0.6 module_C | reserved |
| m04-C5 | module_04 | MED | `ract sidecar reheader` verb (legacy sidecar rewriter) | v0.6 module_C | reserved |
| m04-C7 | module_04 | PROCESS | SP prompt splitting pattern doc | process-doc | reserved |
| m04-C8 | module_04 | PROCESS | Pytest fixture: reset ambient ContextVar between tests | v0.6 module_D `test_hygiene` | reserved |
| m04-C9 | module_04 SP | MED | `RACT_*` consumer enumeration gate (single registry) | v0.6 module_C | reserved |
| [m05-C10](#m05-c10) | module_05 co-build | MED | Machine-identity HMAC in verify sidecar | v0.6 module_E `sidecar_hmac` | reserved |
| m05-C11 | module_05 SP | LOW | `expected_max_size` hint in verify sidecar for concurrent-write detection | v0.6 module_E | reserved |
| [m05-C12](#m05-c12) | module_05 co-build | HIGH | External anchor for mid-file tamper (dedicated module) | v0.6 module_F `manifest_anchor` | reserved |
| m05-C13 | module_05 | PROCESS | SP dispatch splitting pattern for surfaces > 40 KB | process-doc | reserved |
| m05-C14 | module_05 SP | LOW | `read_all_events(memory_budget_bytes=...)` kwarg | v0.6 module_E | reserved |
| m05-C15 | module_05 SP | LOW | Empty-line DoS documented but unmitigated | v0.6 module_E (paired with C12 anchor) | reserved |
| DA-B F-4.3 | audit DA-B | LOW | Group-commit / fsync coalescing on trace writer | v0.6 module_E | reserved |
| DA-B F-5.4-followup | audit DA-B | INFO | Content-hash disambiguation for on_moved (escalate if telemetry shows stale reads inside the current existence-check window) | v0.6 module_G `watcher_hash_disambig` | reserved |
| Ox M-3 | audit DA-A Ox | MED | Chained-anchor backfill for pre-module_09 ledger prefix | v0.6 module_F | reserved |
| m06-Q8 | module_06 Ox Q8 | PROCESS | Closed-IP wordlist scan adjudication policy (pre-committed pass/fail criteria) | process-doc | reserved |

## Expanded notes for the highest-severity rows

<a id="m02-m3"></a>

### m02-M3 — sandbox_env allowlist trust-tier redesign

Repo-committed `.ract/sandbox_env.allowlist` is trusted by default in
v0.5.2. Ox Alpha M-3: a compromised model that landed a PR extending
the file could subvert the entire library-injection defense that
module_02 was built to close. The v0.6 answer: allowlist file must
carry a Rootknot v4 attestation signed by an operator-controlled
SessionKey (or refuse with a clear error). Repo-committed allowlist
file no longer trusted by default. ADR-0048 already reserves the
identifier.

Interlock: the trust-tier module MUST land BEFORE any operator can
be told "your sandbox_env allowlist is honored" -- otherwise the
v0.5.2 partial trust is a bigger footgun than the pre-v0.5.2 no-
allowlist state. If v0.6 slips, roll the allowlist read-path behind
a `--dangerously-trust-allowlist-file` opt-in flag.

<a id="m04-c4"></a>

### m04-C4 — `--strict-sidecar-headers` CLI flag

Additive operator UX for reviewers who want the strict header
demand made visible. v0.5.2 asserts header presence in unit tests
but does not surface the demand on the CLI. First pull-forward
candidate for v0.6 if the C-1 universal sweep lands early.

<a id="m05-c10"></a>

### m05-C10 — machine-identity HMAC in verify sidecar

Fork 1 (a) rejected during module_05 co-build in favor of a
walker-level run_id check. The HMAC would additionally close the
run_id-reuse-across-sessions scenario at the sidecar level (the
current defense assumes the walker walks; a caller that bypasses
the walker still gets a bare-run_id match). Pair with C11.

<a id="m05-c12"></a>

### m05-C12 — external anchor for mid-file tamper

The single biggest unclosed gap from module_05: the current verify
sidecar sits on the same filesystem as the trace log, so an
attacker who can write the log can also write the sidecar and
forge a `verified_head`. The manifest ledger already carries a
`prev_ledger_hash` chain (module_07); the v0.6 answer is periodic
anchor commits from the trace writer INTO the manifest ledger, so
detection of mid-file tamper does not depend on the sidecar being
honest. Ships as its own module in v0.6 -- do not fold into a
mixed-concern module.

## Cross-references

- The DA-A finding set that seeded modules 01/02/03 lives at
  `_BUILD/audit_2026-08-22b/DA_A_rootknot_substrate.md`.
- The DA-B finding set that seeded modules 04/05/06 lives at
  `_BUILD/audit_2026-08-22b/DA_B_runtime_trace_memory.md`.
- v0.5.2 module fragments (which include the flagged-carryover
  citations) live under `_BUILD/ract_v0.5.2_hardening/module_0N.md`.

Note: `_BUILD/` is gitignored; the citations here are pointers for
operators who have a local copy of the deep-audit pipeline. The
findings themselves are also summarised in `CHANGELOG.md` under the
v0.5.2 section.
