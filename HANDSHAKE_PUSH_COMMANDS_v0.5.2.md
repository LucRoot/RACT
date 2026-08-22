# HANDSHAKE REQUIRED
# Operator must explicitly execute the following commands manually after verification.
# DO NOT PIPE THIS FILE TO A SHELL. DO NOT AUTOMATE THIS.
# Claude has NOT authorized push. Operator authorization is required per RACT invariant five.

# v0.5.2 (Deep-Audit Hardening) handshake-gated push commands

## Not yet authorized

Per RACT invariant five (no push without operator handshake), the v0.5.2
hardening pipeline prepared the release-close state, created the local
`v0.5.2` annotated tag, and created the local `backup-v0.5.1-preHardening`
backup tag — but did NOT push. After the operator confirms the handshake
in chat, run the commands below in order from the repo root
(`C:/RootClaw/RACT`). Unlike the v0.5.1 handshakes this is a FIRST-TIME
tag creation for `v0.5.2` (not a re-tag), so no `--force` is needed on
the tag push and no `--force-with-lease` is needed on the branch push
(the v0.5.2 commits are strictly ahead of v0.5.1 with no rewriting).

## Prepared state (at module_06 close)

- **New tag name:** `v0.5.2`
- **New tag body:** annotated, ≤500 chars, matches the operator convention.
- **Backup tag preserved locally:** `backup-v0.5.1-preHardening` at
  `300f8b22e5814e1a663f1a36cd2311b7670595fc` (the v0.5.1 tag tip
  BEFORE module_01 began). Created at the module_06 open, before
  the version bump commit. Recoverable via
  `git checkout backup-v0.5.1-preHardening`.
- **Version surface (SP Q1 fold — was "triple", attested at four
  paths):** `pyproject.toml [project].version` +
  `src/ract/__init__.py __version__` + `VERSION` (human-readable
  banner file) + `tests/test_release_surface.py` version-alignment
  assertions all read `0.5.2`. `ract --version` prints
  `RACT 0.5.2`. The `# RACT 0.5.X` trailing comments per source
  file are historical origin markers (see prior-release
  precedent) and are NOT updated on a hardening bump.
- **Golden hash:** re-locked at module_06 close per Ox-Alpha co-build
  Q2 verdict (narrated re-pin, not silent). Old value:
  `7d6c8b1c56449bb96428e6ba75af2b24b85adadb66e75ca6b2c7a0ad7afc41fb`.
  New value:
  `e8be3860fc36ca4ea3c646c4e5f1d2c12f74d7050df36b478771fafdcbc99306`
  (SP Q3 fold: stated inline so the doc is a verification artifact
  the auditor can compare against
  `src/ract/source_digest.py::GOLDEN_HASH_CONSTANT` at the tagged
  commit). Shift covers SIX hardening modules that touched
  `src/ract/` (SP Q3 fold; was "five" -- off-by-one):
  module_01 (Rootknot v4 hardening), module_02 (sandbox_env
  allowlist), module_03 (subagent lifecycle), module_04 (run_id
  continuity + sidecar header primitive), module_05 (trace log
  durability + honest verify), module_06 (memory system polish +
  docs + release close). See the v0.5.2 CHANGELOG entry.
- **Branch:** `main` at HEAD == release-close commit.
- **Push target:** operator's origin (no remote assumed by this file;
  operator selects at push time).

## Semver rationale

This is a NEW `v0.5.2` release (bump from `v0.5.1`). The bump is
justified by the fifteen deep-audit findings closed as primary work
(new defenses shipped) and the two new CLI verbs (`ract trace verify`
+ `ract memory verify-consistency`) plus the new `--min-schema` +
`--min-schema=N` flag surface. No wire-format break: v0.5.1 payloads,
trace logs, and sidecars remain readable. See `docs/UPGRADING.md`
for the full operator-visible change list.

## Push commands (operator-executed after handshake)

Commands below assume the operator's origin remote is literally named
`origin`. If a different remote name is in use, substitute it
throughout (SP Q2 fold: prior "no remote assumed" text was
inconsistent with the hardcoded `origin` in the commands; the doc
now explicitly names the assumption). Verify remotes first with
`git remote -v` if unsure.

Run in this order:

```bash
# 1. Publish the branch state (release-close commit is at HEAD).
git push origin main

# 2. Publish the v0.5.2 annotated tag.
git push origin v0.5.2

# 3. Publish the backup tag so anyone who cloned during the
#    v0.5.1 window can find the pre-hardening tip.
git push origin backup-v0.5.1-preHardening
```

No `--force` used — no history is being rewritten and the v0.5.2
commits + tag are strictly ahead of every remote reference.
If `git push origin main` is refused as non-fast-forward, that
indicates a concurrent push arrived out-of-band (NOT a v0.5.2
defect); investigate before force-pushing.

## GitHub release notes body

Copy-paste the markdown block below into the "Release notes" field
of the GitHub release authored against tag `v0.5.2` (web UI at
`https://github.com/<owner>/<repo>/releases/new?tag=v0.5.2`).

Alternatively via `gh` CLI: save the block below to a file (e.g.
`/tmp/v0.5.2-notes.md`) and run
`gh release create v0.5.2 --title "v0.5.2 -- Deep-Audit Hardening" --notes-file /tmp/v0.5.2-notes.md`.
The `--notes-file` flag expects an on-disk PATH, not an inline
excerpt (SP Q2 fold: prior text said `--notes-file <this excerpt>`
which would fail on paste since "<this excerpt>" is a placeholder,
not a file).

Release notes body:

```markdown
## RACT 0.5.2 — Deep-Audit Hardening

Fifteen paired Ox-Alpha-partnered deep-audit findings closed across six
hardening modules layered on the v0.5.1 spec-completeness tag.

**Highlights**

- Rootknot v4 signature hardening (module_01): post_init v4 gate,
  authoritative verifier-side cross-check, `min_acceptable_schema_version`
  policy with new `--min-schema=N` CLI flag, and a closed
  known-schema-versions allowlist.
- Sandbox env library-injection defense (module_02): 40+ new
  library-injection env vars added to NEVER_PASSTHROUGH, including
  `LD_PRELOAD`, `DYLD_INSERT_LIBRARIES`, `PYTHONPATH`, `NODE_OPTIONS`,
  `BASH_ENV`, `GLIBC_TUNABLES` (CVE-2023-4911), `GIT_SSH_COMMAND`,
  `HTTPS_PROXY`, and more.
- Subagent lifecycle + PID-reuse hardening (module_03): spawn-time
  `creation_time_ns` capture, tri-state PID identity check
  (SAME / REUSED / DEAD), unconditional tree-kill on dispose.
- Run_id continuity + sidecar schema binding (module_04): new
  `write_sidecar_header` primitive (envelope + tmp+rename atomicity),
  `RACT_RUN_ID` env plumbing through subprocess subagents,
  bootstrap-from-env at subagent boot with synthetic-orphan
  fall-through.
- Trace log durability + honest verify (module_05): per-run
  `{run_id}.verify.json` warm-verify sidecar (O(delta) not O(N²)),
  streaming `iter_events` generator, torn-tail UTF-8 replace,
  universal newline handling, and the ONE `TraceVerifyResult` frozen
  dataclass every verify entry point returns. New CLI verb
  `ract trace verify`.
- Memory system polish + docs + release close (module_06): honest
  dataclass grouping docstring, on_moved reorder-race defense, new
  `ract memory verify-consistency` verb + `IndexConsistencyReport`
  dataclass, plus three MUST-FOLD carryover items (module_01 Q3
  unknown-sidecar refusal, module_04 C-6 RACT_RUN_ID boundary regex).

**New event kinds** (all additive): `substrate.subagent.tree_kill_invoked`,
`substrate.subagent.pid_reuse_detected`, `substrate.subagent.orphan_reaped`,
`runtime.run_id.env_injected`, `runtime.run_id.env_rejected`,
`runtime.run_id.env_stripped_from_parent`, `runtime.run_id.orphan_generated`,
`sidecar.header.written`, `sidecar.header.missing_refused`,
`sidecar.header.mismatch_refused`.

**Compatibility:** v0.5.1 payloads, sidecars, and trace logs continue
to load unchanged. `min_acceptable_schema_version` defaults to 3.
Full migration walk-through in `docs/UPGRADING.md`.

**v0.6 backlog:** twenty-one deferred items routed to
`docs/RACT_v0.6_BACKLOG.md`.

Full change list: [CHANGELOG.md](./CHANGELOG.md#052---2026-08-22--deep-audit-hardening).
```

## Handshake requirement

Per RACT invariant five, an operator must confirm in chat that these
push commands are authorised before they are run. This markdown file
is a preparation artifact, not authorisation. No hardening-pipeline
module code path performs, or shells out to perform, `git push`.
Search: `grep -rn "git push" src/ _BUILD/ract_v0.5.2_hardening/*.md`
returns only this file (as a documentation artifact quoted for the
operator).
