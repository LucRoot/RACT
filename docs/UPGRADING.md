# Upgrading RACT

## v0.5.1 → v0.5.2 (Deep-Audit Hardening)

v0.5.2 is a hardening release. Fifteen deep-audit findings are
closed across five hardening modules plus a release-close module.
No wire-format break: v0.5.1 payloads, sidecars, and trace logs
remain readable. A short list of operator-visible changes and the
few migration steps follows.

**tl;dr — most operators do nothing.** Upgrade the package,
optionally re-run `ract memory verify-consistency` to see the new
verb work, and read the CHANGELOG entry for the finding-level
summary. WARN lines may appear on first ambient run against a
poisoned parent env; that is the new
`runtime.run_id.env_rejected` gate doing its job.

### Version reporting

```
ract --version
# RACT 0.5.2
```

The `__version__` in `src/ract/__init__.py`, the `version` field
in `pyproject.toml`, and the CLI banner all now equal `0.5.2`.

### Payload / sidecar / trace compatibility

- **Rootknot sidecars** — v1, v2, v3, and v4 payloads continue to
  load unchanged. The `min_acceptable_schema_version` policy
  defaults to `3` (module_01), matching v0.5.1 behavior.
  Operators who want strict v4-only should pass
  `--min-schema=4` (new CLI flag in v0.5.2). A `sidecar/v9` or
  other unknown `schema` literal now REFUSES rather than
  silently downgrades to v1 (module_06 fold of module_01 Q3).
- **Trace event logs** — v0.5.1 files continue to read. On first
  `ract trace verify` a fresh `<run_id>.verify.json` sidecar
  auto-generates so subsequent verifies take the warm-path
  (incremental) short-circuit.
- **Trace log torn tails** — files with an aborted final write
  now surface as `status: TORN_TAIL` (exit code 0, chain is
  resumable) rather than raising `UnicodeDecodeError`. Callers
  that grep exit codes see 0 remain 0 for the healthy + torn
  cases.

### New CLI verbs / flags

- `ract trace verify <run_id>` — verify the on-disk event chain.
  Warm sidecar by default; `--cold` re-verifies from GENESIS.
  Exit codes: 0 = VALID or TORN_TAIL; 1 = INVALID; 2 = TAMPERED;
  3 = no event log at path. `--json` emits the full
  `TraceVerifyResult` payload.
- `ract memory verify-consistency [repo_path]` — cross-index
  consistency check (module_06 addition). Exit codes: 0 =
  CONSISTENT; 1 = INCONSISTENT; 2 = UNAVAILABLE. `--no-disk-check`
  skips the missing-file probe; `--json` emits the full report.
  Requires a populated `.ract/memory/symbols.db` (run `ract memory
  init` first).
- `ract provenance verify --min-schema=N` — reject any sidecar
  whose `schema_version` is below N. Default off; passing
  `--min-schema=4` enables strict v4-only deployment.

### New event kinds

Consumers of the trace-event stream may see these additional
`kind` values in v0.5.2. All are additive; the LEGAL_EVENT_KINDS
frozenset admits every v0.5.1 kind plus the new set.

| Kind | Emitter | Payload highlights |
|---|---|---|
| `substrate.subagent.tree_kill_invoked` | module_03 | `pid`, `creation_time_ns`, `path` |
| `substrate.subagent.pid_reuse_detected` | module_03 | `stored_pid`, `stored_ctime`, `current_ctime` |
| `substrate.subagent.orphan_reaped` | module_03 | `count`, `pids` (capped 32) |
| `runtime.run_id.env_injected` | module_04 | `run_id`, `child_pid`, `source` |
| `runtime.run_id.env_rejected` | module_06 (m04 C-6 fold) | `reason` (≤80 chars), `child_pid`, `source` |
| `runtime.run_id.env_stripped_from_parent` | module_04 | `stripped_key`, `stripped_value_hash` |
| `runtime.run_id.orphan_generated` | module_04 | `synthetic_run_id`, `reason`, `child_pid` |
| `sidecar.header.written` | module_04 | `path`, `sidecar_type`, `schema_version`, `run_id` |
| `sidecar.header.missing_refused` | module_04 | `path`, `reason` |
| `sidecar.header.mismatch_refused` | module_04 | `path`, `header_run_id`, `expected_run_id` |

### New exception types

Direct API consumers may catch:

- `ract.core.rootknot.RootknotSchemaViolation` — v4-label without
  v4-fields (module_01).
- `ract.core.provenance.RootknotUnknownSidecarFormat` — unknown
  named sidecar `schema` (module_06 fold of module_01 Q3).
- `ract.runtime.RunIdFormatError` — supplied run_id failed the
  `^[A-Za-z0-9_-]{1,240}$` boundary regex. Note: the
  runtime's own `bootstrap_ambient_from_env` catches this and
  falls through to orphan-generate; the exception is exported for
  callers that want strict handling.

### New result types

- `ract.trace.verify.TraceVerifyResult` — the ONE frozen
  dataclass returned by every trace-log verify entry point.
  Closed `status: Literal["VALID","INVALID","TORN_TAIL",
  "TAMPERED"]`. `.is_valid` = chain is resumable (VALID or
  TORN_TAIL); `.is_healthy` = pristine (VALID only).
- `ract.memory.verify_consistency.IndexConsistencyReport` — frozen
  dataclass mirroring the TraceVerifyResult protocol shape.
  Closed `status: Literal["CONSISTENT","INCONSISTENT",
  "UNAVAILABLE"]`. Carries `inconsistencies: tuple[
  IndexInconsistency, ...]` for domain-specific detail.

### Migration steps (typical operator path)

1. `pip install -U ract` (or your preferred install mechanism).
2. Confirm the version bump: `ract --version` prints
   `RACT 0.5.2`.
3. (Optional) Regenerate cached memory indexes if you have not
   run them in a while: `ract memory init`.
4. (Optional) Sanity-check cross-index consistency:
   `ract memory verify-consistency`. A `CONSISTENT` result means
   the memory tri-store agrees with itself.
5. (Optional) Sanity-check any long-running trace logs:
   `ract trace verify <run_id>` — warms the incremental sidecar
   and returns `VALID` for a clean chain.

No configuration changes are required. Existing sandbox env
allowlists continue to be trusted (with the caveat that the
`.ract/sandbox_env.allowlist` trust-tier redesign is queued for
v0.6 -- see `docs/RACT_v0.6_BACKLOG.md`).

### Behavioral changes that MAY surface a WARN

These lines are the new defenses doing real work, not new bugs:

- `[ract] rejected RACT_RUN_ID env value ...; generating orphan`
  -- a parent process passed a `RACT_RUN_ID` env value that
  failed the boundary regex. The subagent falls through to
  synthetic-orphan generation (v0.5.1 behavior; v0.5.2 adds the
  format validation gate).
- `[ract] sidecar.header.missing_refused ...` -- a legacy
  headerless sidecar was refused in strict mode. Default mode
  falls through with a warn only.
- `[ract] substrate.subagent.pid_reuse_detected pid=... stored_ctime=...`
  -- a subprocess subagent was disposed AFTER its pid was reused
  by an unrelated process. The dispose refuses to signal the new
  tenant. If this fires on a healthy long-running system,
  investigate for PID pressure or process-table exhaustion.

### Rollback

`git checkout backup-v0.5.1-preHardening` restores the v0.5.1 tip
prior to module_01. `git checkout v0.5.1` restores the v0.5.1 tag
proper.

Both tags are locally created only; no push. See
`HANDSHAKE_PUSH_COMMANDS_v0.5.2.md` for the operator's push +
tag ceremony.
