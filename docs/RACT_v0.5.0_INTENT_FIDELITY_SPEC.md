# RACT v0.5.0 Intent-Fidelity Pipeline Spec

**Version:** 0.5.0 (pipeline guidance)
**Predecessor:** restoration clusters 1 + 2 (`_BUILD/ract_v0.5.0_restoration/`, completed 2026-07-28)
**Tag target:** `v0.5.0`
**Prepared for:** Lucas Root
**Sacred:** rootknot (concept). Carried forward from v0.4.0-rc1 with all three signatures intact; this pipeline does not re-shape the schema.

---

## Why this pipeline exists

This is not a new-feature build. It is a walk-back pass over every prior era of the codebase, era by era, module by module, with one question held in front of each change: does the shipped behavior match the intent the era stated when the change first landed?

The sentinel finding is the template. Restoration clusters 1 and 2 caught eleven cases where something was removed for one local reason and the purpose the removed thing served did not get replaced. The removal was accurate in its own frame. The replacement obligation was silent. Nothing in the DoD of the removing module was set up to catch it, because the DoD was written against the change, not against the purpose. Author-name discipline, event-trace fidelity, provenance surfacing, and pre-commit gate wiring all had episodes of this shape.

Intent-Fidelity extends the same audit shape to every era systematically. Each module in this pipeline picks up one era, reads that era's own stated intent out of its master spec and its ADRs, and then verifies that the current tree actually exhibits that intent as behavior. Drift becomes a fix commit. Drift the module cannot close becomes a new ROADMAP item plus an honest gap log entry. Nothing is silently dropped and nothing is silently declared working when only the tests are green.

The frame is "working as intended," not "working as built." A test suite that passes against a shim while the shipped code no longer honors the intent it was written for is exactly the failure mode this pipeline is here to catch.

---

## Non-negotiable invariants

These hold across every module. A module that would break any of them halts and files a note to the ledger before proceeding.

1. **Rootknot is sacred.** The three-signature schema (generator, environment, anti-lazy) lands with v0.4.0-rc1 and carries forward unchanged. No signature added, no signature removed, no schema bump. The sidecar compatibility reader path for v1/v2/v3 stays intact.
2. **No touch to closed-IP.** [REDACTED], Cognify, and any other operator-side project referenced elsewhere in the memory system are out of scope. A module that finds it needs to modify a closed-IP artifact halts and hands the request back to the operator.
3. **Every change verified by test.** Each module's DoD is a boolean. Fix commits carry the test that would have caught the drift the first time. Drift that cannot be reduced to a test becomes a ROADMAP entry and a note, not a silent pass.
4. **Every era's intent captured in writing before modifying.** Each module fragment states the era's intent verbatim from its master spec first, then the delta the current tree exhibits versus that intent, then the fix plan. Prose reordering is denied. Intent-first, delta-second, plan-third.
5. **No push without operator handshake.** Invariant six from v0.4.0-rc1 carries forward. module_08 prepares release state locally, yields to the operator, and the push to `github.com/LucRoot/RACT` executes only after handshake.
6. **Cross-family Second Pass discipline accounts for ecosystem drift.** The v0.4.0-rc1 pipeline logged five reviewer-drift events on eight modules because the endpoints named in the plan were unavailable at dispatch time. That ecosystem drift is now a standing condition of the pipeline: NVIDIA `reason_deep` is end-of-life 2026-08-07; OpenRouter `reason_r1_latest` is missing from the current dispatcher catalog; Google `flash_reason` daily budget exhausts under heavy use; Mistral has a 30K daily token cap. Every module fragment names a primary reviewer plus a documented fallback, both cross-family from the producer.
7. **Author-name-free discipline persists.** The v0.5.0 restoration cluster 1 sentinel finding removed `__root_author__` and its call sites. No module in this pipeline reintroduces the author-name field, its shim, or any test that would silently authorize its return. This is one of the eleven restored purposes and the pipeline exists in part to hold that line.

---

## Module map

- **module_01** — v0.1.x era intent-fidelity. Trust and tooling: dead-code auction, Fence, consolidation pass, rot report, provider routing surface. Verify each still exhibits the trust-boundary intent the v0.1 series stated when it landed.
- **module_02** — v0.2.0 REBUILD era. Signed Rootknot origin, RK-1 and RK-2 invariants, assumption registry, T1 through T7 loop controller, threat model, versioned plan schema, eval harness first cut. Verify the invariants still hold and the assumption registry is still authored on new work.
- **module_03** — v0.3.0 REBUILD era. Auditability and depth: `PROVENANCE.md`, independence lint, benchmark harness, `SessionKey.rotate`, provenance verify CLI, executor wiring. Verify each surface still surfaces the audit signal the era stated.
- **module_04** — v0.4.0 SUBSTRATE era. All sixteen SUBSTRATE §11 signals. Special attention to signals 4 and 5, which the v0.4.0-rc1 close carried forward as PARTIAL because the shim wires the manifest through un-sandboxed. Land the shim upgrade or extend the honest-gap log with the concrete reason the upgrade is not landing here.
- **module_05** — v0.4.0 ALM era. All sixteen ALM §13 signals. Verify AL-1 holds. Verify the eight gates fire in real runs, not just in fixtures. Reconcile the endpoints_SKILL scoping against the actual reviewer catalog given the five reviewer-drift events documented at v0.4.0-rc1 close.
- **module_06** — v0.4.0-rc1 audits era. Re-verify the retroactive-endpoints fixes still hold. Re-grep the [REDACTED] wordlist across every tracked file, every commit message under the tag, and the annotated tag itself for zero hits. Re-verify the functionality-audit fixes did not silently regress under later commits.
- **module_07** — Restoration clusters 1 + 2 era. Verify all eleven restored purposes actually persist in behavior, not just in green tests. Author-name absence, event-trace fidelity, provenance surfacing, and pre-commit gate wiring each get a behavior probe.
- **module_08** — v0.5.0 close. Combined CHANGELOG `[0.5.0]` entry, README refresh, VERSION plus pyproject plus `__init__` set to `0.5.0`, `docs/ROADMAP.md` compiled from every prior era, combined 43-signal sweep plus per-module intent attestations, tag `v0.5.0` locally, then HANDSHAKE-GATED PUSH to `github.com/LucRoot/RACT`. The module prepares state, yields to the operator, and the push runs only after handshake.

---

## Bar policy

The DoD in this pipeline is different from prior pipelines. It reads: "intent verified as actual behavior of the current tree."

- **Intent-first.** Every module fragment opens with the era's stated intent, quoted from its master spec. That quote is the audit anchor. The module does not rewrite it.
- **Delta-second.** The module then documents where the current tree drifts from that intent. Drift is the working queue.
- **Fix-third.** Every delta gets one of two outcomes:
  - **Drift becomes a fix commit.** The commit carries the test that would have caught the drift the first time. The DoD re-verifies after each fix commit.
  - **Unresolvable drift becomes a new ROADMAP item plus an honest gap log entry.** The gap is named concretely, the reason it cannot close here is named concretely, and the responsible owner is named. Nothing is silently dropped.
- **No DoD softening.** A module that finds its DoD infeasible halts and surfaces the reason to the operator; it does not lower the intent to what the module happens to have produced. This is the same halt-and-file rule the prior pipelines carried, restated so it survives compaction.

---

## Cadence and watchdog

- **Cadence:** per-sub-task. Every step within a module externalizes state to `build_state.md` before advancing. No multi-step in-flight state that only exists in the model turn.
- **Watchdog:** cron. The main session registers the cron id at kickoff and logs it in the ledger's Status log. The resume pulse reads `active_module` from the frontmatter and continues at that module's first not-yet-DONE step.
- **Self-halt on close.** When `current_status: complete` fires in the frontmatter, the cron self-halts. The pipeline does not need a separate deregister action.
- **Advance rule.** Module transitions happen only when the current module's DoD is boolean-passing, its fix commits are landed, and its honest-gap log entries are written.

---

## Signals checklist for pipeline close

module_08 does not tag `v0.5.0` and does not yield to the push handshake until every one of the following is `true`.

- [ ] All 43 signals from v0.4.0-rc1 evaluate true against the v0.5.0 tag commit (11 REBUILD + 16 SUBSTRATE + 16 ALM). The honest count of 43 (not 46) that v0.4.0-rc1's CHANGELOG `### Verify` reconciled remains the total; no new signals were added in this pipeline.
- [ ] Each module fragment carries a `## Intent verification results` section with a verdict per intent statement quoted from the era's master spec.
- [ ] Full test suite passes at the tag commit, with the baseline three pre-existing v0.3 test failures explicitly excepted and named in the ledger.
- [ ] `VERSION`, `pyproject.toml` `[project].version`, and `src/ract/__init__.py` `__version__` all resolve to `packaging.version.Version("0.5.0")`.
- [ ] `CHANGELOG.md` carries a `[0.5.0]` entry with a bullet per era covered (v0.1.x, v0.2.0, v0.3.0, v0.4.0 SUBSTRATE, v0.4.0 ALM, v0.4.0-rc1 audits, restoration clusters 1+2) plus a bullet per module fix commit.
- [ ] Tag `v0.5.0` exists on the final commit as an annotated tag naming the intent-fidelity scope.
- [ ] `docs/ROADMAP.md` compiled from every era's honest-gap log carries forward; nothing dropped from the v0.4.0-rc1 backlog silently.
- [ ] No closed-IP terms in tracked files, commit messages under the tag, or the annotated tag body. Re-verified at close via the wordlist scan the v0.4.0-rc1 audit established.

---

## Reference set

The closed list of public sources this pipeline's design draws from. Any design decision inside a module fragment must cite this set.

**Skills** (from `C:\RootClaw\docs\Skills\`):

- `pipeline_bootstrap_SKILL.md`
- `depth_chain_SKILL.md`
- `lateral_chain_SKILL.md`
- `endpoints_SKILL.md`
- `watchdog_SKILL.md`
- `spec_SKILL.md`

**Prior pipeline master specs:**

- `docs/RACT_v0.2.0_REBUILD_SPEC.md`
- `docs/RACT_v0.3.0_REBUILD_SPEC.md`
- `docs/RACT_v0.4.0_SUBSTRATE_SPEC.md`
- `docs/RACT_v0.4.0_ANTILAZY_SPEC.md`

**ADRs:**

- Every ADR under `docs/ADRs/`. The pipeline reads each ADR's context and consequence sections as an intent source per module.

**Signal checklists:**

- SUBSTRATE §11 signals (sixteen items, module_04 anchor).
- ALM §13 signals (sixteen items, module_05 anchor).
- REBUILD §4 signals (eleven items, module_02 and module_03 anchor).

**Prior sovereign records:**

- `_BUILD/ract_v0.4.0_antilazy/SOVEREIGN_CHANGELOG.md` (the operator-only truth-carrier for v0.4.0-rc1 including the Grove-Forge removal and the [REDACTED]-leakage audit reversal).
- `_BUILD/ract_v0.5.0_restoration/` (the eleven restored purposes from clusters 1 and 2; the direct predecessor).

Anything outside this closed list needs a note in the module fragment before it enters the design.

---

## Closing

The prior pipelines built the substrate and layered the anti-lazy gates on top. This pipeline reads what those pipelines said they were doing and checks whether the current tree still does it. A change that removed a thing without replacing its purpose is exactly the failure mode this pipeline exists to catch. Eleven such purposes surfaced from the two restoration clusters alone. The rest of the eras get the same walk-back treatment here, one era per module, intent-first, then delta, then fix.

Working as intended, not working as built. That is the bar.
