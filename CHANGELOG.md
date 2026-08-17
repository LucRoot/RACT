:warning: This file is project documentation, not part of the source code.

# Changelog

All notable changes to RACT (Root Agentic Coding Tool) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
