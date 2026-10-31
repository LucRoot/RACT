# Upgrading RACT

## From 0.5.2

Checked with a workspace that v0.5.2 made, opened by this branch. The test is
`tests/integration/test_upgrade_from_v052.py`. It runs the v0.5.2 tree from its
git tag, with the fake model server; nothing is installed.

### What carries over

- Config. A v0.5.2 `ract.yaml` loads, and `ract doctor` exits 0.
- Sessions. A session file written by the v0.5.2 session store is read here
  without error. (The store was written by the old code directly, because a
  one-shot run does not save a session and no terminal was available.)
- History. `ract report --last` prints a plain answer and no traceback. A
  one-shot run leaves no loop report, so it says so.
- Corrupted files. A session file that is not JSON gives no traceback.

### What changes

- A failed command that RACT ran in a turn (a named test, or a build, lint,
  typecheck or format run) now keeps the turn from "done": the outcome is
  `failed`, the process exits 1, and the verdict names the command. A script
  that read exit 0 after a red test now sees 1.
- The turn summary's first line reads `verdict: ...`; when the turn ran a
  command it is followed by where the command records are kept.
- `ract run --loop --yolo` exits with the code of the cause that stopped the
  loop (for example 4 when it ran out of iterations, 3 for a prompt that
  changed mid-run), where it used to exit 0 for every stop except a
  regression.
- `ract policy sign` shows what the policy allows and asks `y` before the
  passphrase, and every `ract policy` command acts on the folder that holds
  `ract.yaml` (or the git root), named on its first line.
- `max_mode: unrestricted` in `.ract/policy.yaml` is refused at load.
- A turn that changes files says `signed` only when each changed file's
  Rootknot verifies; on Linux with bubblewrap, a tier-3 command runs inside
  it, and `ract doctor --sandbox` says so.
- A handshake you approved before this change no longer widens a run's
  capability manifest. Approve it again with `ract handshakes approve
  <milestone-id>`. An approval now counts only when this machine recorded it,
  in the user state directory, so a `.ract/handshakes.json` that a repository
  ships cannot approve anything (S-035).
- `ract run "<intent>"` asks before it changes a file. In a terminal it asks
  the plan question and the step question. With no terminal (a script or a CI
  job) it does not change files: it stops with exit 3 and says so; questions
  that write nothing still run. A script that ran `ract run` to change files
  adds `--yolo`, or moves to `ract -p "<intent>" --accept-edits`. `ract run
  --loop` needs `--yolo` until the loop can ask (D-104).
- A step no longer commits onto your branch. v0.5.2 committed each step
  (`rootact step 1: ...`) onto the branch you had checked out. This branch
  leaves the change unstaged. `tests/integration/test_run_never_moves_user_branch.py`
  checks this; this upgrade test does not repeat it.
- A commit made by v0.5.2 stays in your history. Its `.ract/gravity_index.json`
  is tracked, so `git status` shows it as deleted once RACT ignores it.
- A run on this branch does not show `.ract/` as untracked. The v0.5.2 run did, so
  step 3 below is still the way to stop tracking an old commit's copy.
- `ract handshakes approve <id>` signs the approval with your operator key, so
  it asks for the passphrase at a terminal; create the key once with `ract
  policy keygen`. An approval without that signature (one recorded by an
  earlier version, or by `ract consolidate apply`) is listed as "approved
  (unsigned: unlocks nothing)": it widens no manifest and still blocks the
  step's commit. Approve it again to sign it (ADR-0048 R2).
- Keys leave the project. The intent-recompile key moves from
  `.ract/operator.key` to the user config folder, and the per-run sandbox and
  ALM keys move from `.ract/sandbox/` and `.ract/alm/` to the user state
  folder. The old places are still read in this release, with a warning on
  stderr; `ract policy migrate-keys` moves them and overwrites nothing
  (ADR-0048 R3).

### Not yet checked

These are in the plan for this release. They are not verified by a test yet, so
do not rely on them until they are:

- A repository's own hooks, MCP servers and model endpoint need `ract trust`
  before they run.
- A new session starts in `default` mode.
- `/undo` backups live in the user state directory.

### What to run

1. Check the workspace: `ract doctor`.
2. If v0.5.2 committed a step onto your branch, check the log with
   `git log --oneline -3`. Keep the commit or drop it, as you prefer. RACT does
   not rewrite your history.
3. Stop tracking the RACT state folder if an old commit added it:
   `git rm --cached -r .ract` then commit. Add `.ract/` to `.gitignore` so it
   stays out of `git status`.
4. Move any keys out of the project: `ract policy migrate-keys` in each project
   that has a `.ract/operator.key`, `.ract/sandbox/` or `.ract/alm/`.

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
