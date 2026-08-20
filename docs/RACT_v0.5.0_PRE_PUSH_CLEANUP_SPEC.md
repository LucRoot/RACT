# RACT v0.5.0 Pre-Push Cleanup Spec

**Version:** 0.5.0 (in-place retag; version triple unchanged)
**Predecessor:** v0.5.0 Memory Discipline (tag `v0.5.0` at SHA `0f1e6e9ff32e896dbdbc9875f2fc494379683111` on commit `6d3f076`, closed 2026-08-19)
**Tag target:** `v0.5.0` (retag on cleanup-close commit)
**Prepared for:** the operator
**Sacred:** Rootknot (three-signature schema: generator, environment, anti-lazy). No signature added, removed, or reshaped. Closed-IP wordlist gate at `tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files` stays zero-hit outside the two documented `assets/demo.cast` deferrals. Author-name-free tree stays intact. AL-1 stays enforced. Golden hash locked; this pipeline touches only `docs/` and must not shift the hash.

---

## Origin

Between the Memory Discipline pipeline closing at commit `6d3f076` and the operator handshake to publish `v0.5.0`, a pre-push deep audit surfaced three ship-blockers plus one addendum-worth caveat plus two cosmetic observations. This pipeline folds the three blockers plus the addendum into a single docs-and-metadata cleanup commit, retags `v0.5.0` on the cleanup-close commit, and prepares the handshake-gated push. Nothing under `src/ract/` moves in this pipeline. No new features, no behavior changes, no version bump.

The three blockers:

1. **`docs/USE_CASES.jsonl` missing an accepted entry for the `memory` verb.** Memory Discipline module_09 added `memory` as a top-level CLI verb (routes through `src/ract/cli.py` alongside `run`, `skills`, `mcp`, etc.), and the release-surface gate at `tests/test_use_cases_catalog.py::test_every_cli_verb_is_accepted` requires every top-level CLI verb to have an accepted entry in the catalog. The gate is currently red under a full-suite run. Fix: append one JSON object to `docs/USE_CASES.jsonl` with `title` matching the shipping verb name (the catalog test matches case-insensitively).

2. **`CHANGELOG.md` `Extended` bullet for `enforce_g6` / `enforce_g7` is factually inaccurate.** The current bullet at `CHANGELOG.md:144-146` says these helpers accept `CandidateDiff | None` and that "older call sites that pass no diff receive a no-op pass." The actual behavior at `src/ract/antilazy/pre_commit.py:513-538`: `enforce_g6_edit(diff: CandidateDiff | None, plan, *, step_id=None)` raises `LazinessViolatedError(kind="diff_without_plan")` when `diff is None`. And `enforce_g7_edit(diff: CandidateDiff, companion, *, step_id=None)` at `pre_commit.py:557+` accepts non-Optional. Fix: docs-only rewrite of the bullet to reflect actual behavior.

3. **Annotated tag body for `v0.5.0` runs 948 chars over the operator's 500-char convention.** Module_10 reported 570 chars in its status log; the actual live tag body is 948 chars per `git cat-file -p v0.5.0 | wc -c`. Fix: delete the local tag, recreate it on the cleanup-close commit with a body under 500 chars that drops the "Sacred spine untouched" recap the CHANGELOG already carries.

The one addendum:

4. **`CHANGELOG.md` `Known limitations` needs a `retrieval_attestation` caveat.** The v0.5.0 new `retrieval_attestation` field on Rootknot extends the signed surface with a retrieval-bundle digest that is byte-authentic but not bound to `run_id`, `prompt_hash`, or `workspace_snapshot_digest`. So the DeepSeek REVIEW_2 replay-attack vector logged during Memory Discipline's Rootknot review applies to the new surface unchanged. Not a regression, but the new surface arrives with the same weakness rather than the fix. Fix: add one bullet under `Known limitations` explicitly deferring the unified-payload extension to v0.5.1.

Two cosmetic observations from the same audit fall outside this pipeline:

- Top-level `ract --help` does not list `memory` and `retrieval` because they route through an `intent` positional. Flag as v0.6 UX polish; do not open a v0.5.x blocker.
- `ract.memory.probes.needle` exports a `NeedleProbe` class only; the CHANGELOG does not specify the symbol shape, so no contract violation. Flag as v0.6 UX polish.

---

## Intent

"Completed" for this pipeline means:

- The three ship-blockers plus the one addendum land as a single commit on `main`.
- The `v0.5.0` local annotated tag is deleted and recreated on the cleanup-close commit with a body under 500 chars containing zero closed-IP terms.
- The golden hash stays locked (all edits live under `docs/`; the source digest walks `src/ract/` and must not shift).
- The wordlist gate stays zero-hit outside the two documented deferrals.
- The `HANDSHAKE_PUSH_COMMANDS.md` in this pipeline's build directory points at the retagged `v0.5.0` SHA and lists the two push commands under a `## Not yet authorized` header.
- The pipeline yields to the operator for the push handshake per invariant five carried forward from Memory Discipline.

No new features. No new tests except the regression tests each Second-Pass fold would add if a reviewer surfaces a concrete defect. The pipeline is docs-and-metadata cleanup, and the retag is the release-surface artifact.

---

## Bounded scope

### In scope (this pipeline)

- One accepted entry for the `memory` verb in `docs/USE_CASES.jsonl`.
- One docs rewrite of the `enforce_g6` / `enforce_g7` bullet in `CHANGELOG.md`.
- One new bullet under `Known limitations` in `CHANGELOG.md` for the `retrieval_attestation` binding caveat.
- One tag retag: delete local `v0.5.0`, recreate on the cleanup-close commit with body under 500 chars.
- One handshake-gated push preparation.

### Out of scope (deferred)

- Every v0.5.1 blocker queued during the DeepSeek external review pass carries forward untouched. This pipeline does not open the unified-payload extension for `retrieval_attestation`; the caveat records the deferral and the v0.5.1 pipeline owns the fix.
- Every v0.6 UX polish item (help-listing for `memory` and `retrieval`, `needle_probe` function-shape symbol export, per-module CHANGELOG file manifest, pre-push hook technical safeguard) stays queued.
- No `src/ract/` file moves in this pipeline. If a reviewer's Second-Pass finding requires a `src/ract/` change, this pipeline halts and files an ADR before proceeding.
- No version bump. `VERSION`, `pyproject.toml`, `src/ract/__init__.py` all continue to read `0.5.0`.
- No new event kinds. No new ADRs (the caveat lands as a Known-limitations bullet; no design change requires an ADR).

---

## Sacred spine invariants

Carried forward from Memory Discipline unchanged. Each has a named test file that would fire if the invariant were violated.

1. **Rootknot's three-signature schema stays intact.** Test: `tests/test_release_surface.py::test_rootknot_signature_count_unchanged`. This pipeline touches only `docs/` and `_BUILD/` (gitignored); the signature schema does not move.
2. **Closed-IP wordlist gate stays zero-hit.** Test: `tests/test_release_surface.py::test_no_closed_ip_terms_in_tracked_files`. Every commit in this pipeline is preceded by a wordlist scan; a hit refuses the commit. The pre-existing hits inherited from the Memory Discipline `_BUILD/` tree stay untracked; this pipeline does not introduce new hits.
3. **Author-name-free tree stays intact.** Test: `tests/test_release_surface.py::test_no_root_author`.
4. **AL-1 (anti-lazy signature) stays enforced.** No change to `src/ract/antilazy/`.
5. **Golden hash locked; this pipeline touches only `docs/`.** Test: `tests/test_release_surface.py::test_golden_hash_matches_locked`. The source digest walks `src/ract/`; edits under `docs/` must not shift the digest. The module verifies the hash before commit and after; if it shifts, this pipeline halts.
6. **Rootknot backward compatibility.** Test: `tests/memory/test_rootknot_retrieval_attestation.py::test_older_sidecar_still_verifies`. Unchanged.
7. **Definition of Done is a yes/no test.** Every module's DoD is a boolean checklist a cold reader can execute. Qualitative bullets forbidden.
8. **Local commits only.** No `git push` from the pipeline. Push is handshake-gated per Memory Discipline invariant five.

---

## Module map

Three modules. Module_02 is a placeholder the operator annotates before execution begins.

- `module_01.md` **Audit-finding cleanup fold.** Bundles the four items above into one commit. Retag `v0.5.0` on the cleanup-close commit.
- `module_02.md` **[PLACEHOLDER: operator will annotate before execution.]** Scope, steps, DoD, and reasoning-endpoint scoping to be filled in by the operator. Main-session refuses execution of module_02 in its current placeholder shape.
- `module_03.md` **v0.5.0 close + handshake-gated push.** Rewrites `HANDSHAKE_PUSH_COMMANDS.md` for the retagged `v0.5.0` SHA, verifies the release-surface gates and closed-IP scan at the retag commit, logs the push commands in the ledger's Status log, yields to the operator for the handshake. No push executed by the module.

---

## Bar policy

Same shape as Memory Discipline.

- **DoD is the floor.** Each module's Definition of Done is a boolean checklist a cold reader can execute. When it passes, the module commits.
- **Log Flagged gaps at close.** After the DoD-met commit, the module author fills in the `Flagged gaps (to log at close)` section with what "excellent" would have demanded past the DoD. That log feeds v0.5.1 and v0.6 pipelines; it is never silently dropped.
- **POST-audit Lateral Chain plus Depth Chain mandatory.** Every module fragment carries both a PRE-build and a POST-audit Lateral Chain plus Depth Chain pass, per the discipline the operator introduced during Memory Discipline. PRE-build passes land at scoping time; POST-audit passes land at module close after the Second Pass fold.
- **DoDs are pre-signed by the pipeline, not renegotiated in-module.** A module that finds its DoD infeasible halts, files a note to the ledger's Status log, and yields.

---

## Signals

The Memory Discipline release-surface tests defined 56 signals (11 REBUILD plus 16 SUBSTRATE plus 16 ALM plus 13 MEMORY). This pipeline is docs-and-metadata cleanup; no new release-surface signals are proposed. The signal counts stay at 56.

If a reader wants a tag-body signal for future retag work, one candidate: `test_tag_body_under_operator_max_length` in `tests/test_release_surface.py`. Not required for this pipeline; noted as a v0.6 hardening candidate that would prevent the ship-blocker 3 class of drift from recurring.

---

## Cadence and watchdog

Same shape as Memory Discipline.

- **Cadence:** per-sub-task. Every step within a module externalizes state to `build_state.md` before advancing.
- **Watchdog:** cron. The main session registers the cron id at kickoff and logs it in the ledger's Status log. The resume pulse reads `active_module` from the frontmatter and continues at that module's first not-yet-DONE step.
- **Advance rule:** the resume pulse never invents a new module. If `active_module` is `module_01.md` and step 3 is not yet DONE, the pulse resumes at step 3 of module_01.
- **Halt-and-file rule:** any module that cannot meet its DoD halts, files a note to the ledger, and yields.

---

## Reference implementation notes

### Files touched by module_01 (execution scope, not this scaffolding pass)

- `docs/USE_CASES.jsonl` (+1 line: accepted entry for `memory`).
- `CHANGELOG.md` (edit the `enforce_g6` / `enforce_g7` bullet; add one bullet under `Known limitations`).
- Local git tag `v0.5.0` (delete plus recreate).

No `src/ract/` file touched.

### Retag procedure

1. Confirm the cleanup commit lands on `main` with a clean working tree.
2. `git tag -d v0.5.0` on the local repo.
3. `git tag -a v0.5.0 <cleanup-close-commit-sha> -m "<body under 500 chars>"`.
4. Verify the new tag body with `git cat-file -p v0.5.0 | wc -c` reads under 500.
5. Verify the new tag body with the wordlist scan reads zero hits.
6. Update `_BUILD/ract_v0.5.0_pre_push_cleanup/HANDSHAKE_PUSH_COMMANDS.md` with the new tag SHA.

### Tag body content

The new tag body drops the "Sacred spine untouched" recap the CHANGELOG already carries, drops the enumeration of new event kinds and payload fields (each already enumerated in the CHANGELOG `Added` and `Extended` sections), and keeps only the release name plus the one-line scope summary plus the 56-signal-sweep line plus the v0.6 deferral line. Estimated final size: 380 to 480 chars.

### CHANGELOG rewrite discipline

The `enforce_g6` / `enforce_g7` bullet rewrite is docs-only. It must reflect the actual behavior at `src/ract/antilazy/pre_commit.py:513-590` (module_01 re-reads the source at edit time). The rewrite must not claim behavior the code does not exhibit. If module_01 finds the actual behavior differs from what this spec describes, the module halts and files an ADR.

### Known-limitations bullet discipline

The bullet under `Known limitations` records the deferral of the unified-payload extension for `retrieval_attestation`. It names the field, names the replay-attack vector, cites the DeepSeek external review as the source, and points at v0.5.1 as the fix pipeline. No claim about the fix landing in this pipeline; no claim about a workaround.

### Handshake-gated push preparation

`_BUILD/ract_v0.5.0_pre_push_cleanup/HANDSHAKE_PUSH_COMMANDS.md` sits under a `## Not yet authorized` header carrying the exact two push commands (`git push origin main` then `git push origin v0.5.0`) plus the retagged SHA plus the semver rationale (patch-family retag: no version bump, docs-and-metadata cleanup, unchanged behavior surface). The push executes only after the operator handshake per Memory Discipline invariant five.

---

## Closing note

Memory Discipline shipped the substrate. This pipeline scrubs the release-surface drift the substrate landing accumulated and hands the operator a clean handshake to publish. The three blockers are small; the addendum is small; the tag retag is a one-command operation. The intent is that after this pipeline closes, `v0.5.0` reads correctly to a fresh clone: the CHANGELOG matches the code, the CLI verb catalog matches the shipping surface, the tag body respects the operator convention, and the `Known limitations` list is honest about the deferred fix.

v0.5.1 owns the unified-payload extension for `retrieval_attestation`. v0.6 owns the UX polish backlog. This pipeline owns only the cleanup that stands between Memory Discipline close and the push handshake.
