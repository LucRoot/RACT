# RACT Roadmap

Post-release upgrade queue. v0.4.0-rc1 (2026-07-26) closes the SUBSTRATE
and Anti-Lazy Module (ALM) pipelines with the environment as thorough
verifier; this file compiles the honest-gaps log from every one of the
fourteen combined-pipeline modules plus every deferred deeper-improvement
finding from the ALM Second Passes plus four dispatcher-drift events at
the operator-side dispatcher-scoping boundary.

## v0.5 hardening (from substrate close)

Flagged gaps compiled from `_BUILD/ract_v0.4.0_substrate/module_01.md`
through `module_07.md`. Substrate module_08 was scope-amended to defer
the entire release surface to ALM module_08 (this pipeline); its own
gap log is limited to the executor-adapter shim and is folded into the
substrate module gaps below.

- module_01: live evaluators are stubs; pytest/mypy/hypothesis read metadata, don't execute
- module_01: coverage gate stored but not enforced (no CoverageInvocation kind)
- module_01: IntentCompiler scaffold — no test proposal, no ADR walking, no diff traversal
- module_01: LoopController still runs v0.3 milestone-oracle path, not wired to build_loop_state
- module_01: RunReporter.render_last_loop doesn't include the suite
- module_01: assertion callable_refs not sandboxed (importlib, no allowlist)
- module_01: pre-existing mypy noise in src/ract/executor.py:365,367
- module_01: pre-existing `tests/test_readme_report_formats.py::test_readme_documents_eval_runs` red at HEAD (unchanged since v0.3)
- module_02: substrate CLI is wrapper; SubstrateLoop not the shipped loop default until module_08 shim (config-flag gated)
- module_02: `_fast_forward_head` uses `git reset --hard`, discards untracked files
- module_02: container backends (Dagger/Podman) never contacted live runtime
- module_02: container process-group teardown CLI-scoped; escaped background processes not tracked
- module_02: loop-entry preconditions opt-in (default False)
- module_02: `HandshakeRegistry.blocks_commit` is O(pending × ids); needs indexed lookup
- module_02: `ract session ls` doesn't distinguish BLOCKED_ON_HANDSHAKE from open
- module_02: Windows-case check only on worktree root basename, not deeper segments
- module_02: `SubstrateStepSpec.predicates` typed only as `tuple`, not `tuple[AcceptancePredicate, ...]`
- module_03: Windows OS-enforced sandbox unshipped (no AppContainer + Job Object + WFP backend)
- module_03: `--allow-unenforced-sandbox` is a real escape hatch; no shipped-tag hard-refuse
- module_03: Pydantic wheel absent on exotic architectures triggers sdist build
- module_03: `sandbox.granted`/`sandbox.denied` events drop to null sink until module_05 event log lands (closed in module_05)
- module_03: sandbox key material manifest-referenced; storage layer is module_06 work (closed in module_06)
- module_03: Landlock version drift is runtime probe, not compile-time guarantee
- module_03: pre-flight `would_refuse_*` uses fnmatch, not real path resolution
- module_03: `RACT_TIER_3_ENABLED` constant in source — no signed build attestation
- module_03: no `ract run --manifest` CLI flag yet
- module_04: corpus is 68/75 (schema_compliance short of 40)
- module_04: refusal-fidelity 15-item boolean at 1.00 too unforgiving; needs weighted-severity
- module_04: live-provider CLI path not wired (`--provider openai` returns exit 2)
- module_04: router gate not wired into `ProviderRouter.register`
- module_04: `ract.yaml` schema override for gate thresholds not loaded from CLI
- module_04: response cache TTL is `--refresh`-only; no `--max-cache-age`
- module_04: Anthropic tool-use needs PlannedStep reassembly wrapper before validator
- module_05: OTLP export not proven against live collector in CI
- module_05: `RunReporter.project_events` doesn't map quality_score, token counts, cost, latency
- module_05: `RedactionProfile` is shallow pattern-scrub; no entity-aware DLP
- module_05: replay determinism assumes tool layer deterministic; no divergence detection
- module_05: `prompt.sent`/`response.received` emit only via `send_with_trace`; live CLI unwrapped
- module_05: `tool.called`/`tool.result`/`tool.refused` not auto-emitted by executor dispatcher
- module_06: sandbox key archive per-machine; no `.rack/sandbox/archive/` sync convention
- module_06: schema_version v1→v2 event migration testing not wired
- module_06: RK-3 skipped-with-warning for v1 sidecars is audit gap until strict-mode CI
- module_06: contract-primitive migration reuses v0.3 CLI; needs `ract.contracts.core` refactor
- module_06: `WhispererContract` prompt injection wired at Harness.run planner site (substrate module_08 commit 492296c); coverage across every planner call site TBD
- module_06: `FenceGate.approved_tickets` is process-local class variable; no cross-process store
- module_06: `AuctionSweep` between-iteration wiring lands in substrate module_08 (commit 73b42b8); config-flag toggle across all loop entrypoints TBD
- module_06: rootknot `predicate_results` field carries only digests; RK-3.3 can't assert `ok=True`
- module_06: auction sweep uses O(files) sequential subprocess `git blame`/`git log`
- module_07: `evals/LEADERBOARD.md` has only FakeProvider row; live per-provider rows deferred
- module_07: live-provider E2E path not exercised; nightly `evals-full.yml` gated on `RACT_EVAL_ENABLED`
- module_07: fixture streams cover 3 of 15 pinned problems; other 12 SKIPPED
- module_07: SWE-bench Lite live path doesn't apply git patch nor invoke instance-image harness
- module_07: Polyglot live path doesn't run upstream hidden test suite
- module_07: Conformance/security columns read RESULTS.md files not present in tree
- module_07: Polyglot subset selection assumes historic Exercism categorization
- module_08 (substrate): manifest not attached to the SubstrateLoop the executor-adapter shim constructs; shim-driven runs are un-sandboxed (SUBSTRATE §11 signal 4 PARTIAL)
- module_08 (substrate): no code path writes `<run_dir>/manifest.json` (SUBSTRATE §11 signal 5 PARTIAL)

## v0.5 hardening (from ALM close)

Flagged gaps compiled from `_BUILD/ract_v0.4.0_antilazy/module_01.md`
through `module_07.md`.

- module_01: per-intent G2 threshold override (default 0.7; needs `ract.yaml` per-run overrides)
- module_01: `MutmutSource` adapter is a stub (raises `NotImplementedError`); AST source only today
- module_01: `enforce_g2` wired to shipped loop entry point pending SubstrateLoop-default rollout
- module_01: non-triviality check is byte-shuffle only; metadata-channel perturbations missing
- module_02: per-intent `tau_cov` override (default 0.8; needs `ract.yaml` overrides)
- module_02: cross-language coverage runner is Python-only; Rust/TS hunks logged not gated
- module_02: AST-normalized leakage scan is `--grep`-marker only; no full-tree walk
- module_02: `enforce_g3`/`enforce_g4` wired to shipped loop entry point pending SubstrateLoop rollout
- module_02: `is_trivial_change` bypass cross-step attack not caught by per-step gate
- module_03: `enforce_g5`/`enforce_g6` wired to shipped loop entry point pending SubstrateLoop rollout
- module_03: handshake-approved denials still emit `laziness.violated`; cluster analyzer missing
- module_03: `getattr(module, 'old_name')` is advisory-only, not hard-block (accepted design)
- module_03: stdlib `ast` chosen over tree-sitter; migration is v0.5 ADR when TS/Go/Rust land
- module_04: G7/G8 completion-gate wiring requires `_final_diff_for_gates` hook in `LoopController`
- module_04: anti_lazy conformance fixtures are placeholder; need real mini-workspaces
- module_04: companion adapter interface has no rate-limit backpressure
- module_04: `enforce_trivial_rate_ceiling` is memoryless; callers must persist history in event trace
- module_04: `_extract_keywords` stop-word set is English-only
- module_05: operator handshake UX on partial reversal taint deferred to release close
- module_05: ALM verifier key registry primitive not shipped; no default `.rack/alm/archive/*.key` resolver
- module_05: `LoopController` wiring for Investigator + reversal-scan + gate_results embedding
- module_05: operator's dispatcher-scoping documentation three-family review example not landed (see operator-side gaps below)
- module_05: Investigator per-file probe requires a real `CompanionAdapter` (stub in tests today)
- module_05: silent `except Exception` in trace-emit blocks — add debug-log of suppressed exception
- module_06: cost cap on primary-provider dispatch per rule-like completion (belongs in `ract.yaml`)
- module_06: cross-language iso-perturb solution comparison (Python-only today)
- module_06: `compile_and_detect_rule_like` doesn't persist `rule_like` flag into `suite.json`
- module_07: dedicated G4/G7 fixtures (currently piggy-backing on `weak_assertion_insertion` + `pattern_matching_rule_like`)
- module_07: live-provider reruns across ≥3 provider families (via nightly `evals-full.yml`)
- module_07: antilazy corpus growth cadence — documented process for new reward-hacking incidents
- module_07: `sandbagging_under_effort` needs runner-applies-diff glue for real G8 exercise
- module_07: `sycophantic_reversal_no_evidence` `trace.jsonl` needs exact `response.received` payload
- module_07: PR-tier smoke workflow leaderboard idempotence drift on fresh base reports
- module_07: dedicated PR-tier `iso_perturb` fixture needs deterministic mock companion

## v0.5 hardening (from second-pass deferrals)

Deeper-improvement findings the module-level second-pass reviewers named
but the module deferred rather than landing as a fix commit. Reviewer
identities reflect the ACTUAL dispatcher used (see the operator-side
dispatcher-gaps section for the four plan-vs-actual drift events).

- module_01 (external reviewer via operator dispatcher): ACH 0.79 precision inflates `kill_rate` denominator; ~21% missed equivalents
- module_01 (external reviewer via operator dispatcher): trivial-holdout ceiling insufficient — add compose-time signal + consecutive-similar refusal
- module_02 (cross-family reviewer via operator dispatcher): `_classify_triviality` gameable by mixed-diff (formatter + substantive)
- module_02 (cross-family reviewer via operator dispatcher): 3-run flakiness filter 52% pass at 20% flake; need adaptive N + Wilson interval
- module_03 (external reviewer via operator dispatcher): data-flow escape via `s = pytest.skip; s()` bound-method assignment
- module_03 (external reviewer via operator dispatcher): handshake-approval per-pattern cap absent (`max_handshake_approvals_per_pattern`)
- module_03 (external reviewer via operator dispatcher): no cross-run cluster analysis over `handshake.requested`/`resolved`
- module_03 (external reviewer via operator dispatcher): `SymbolNode` lacks signature info; arg-list/return changes miss under-edit
- module_03 (external reviewer via operator dispatcher): full tree-sitter analyzers for TypeScript/Go/Rust G5/G6
- module_04 (external reviewer via operator dispatcher): companion-matrix vs live conformance staleness (no per-schedule liveness check)
- module_04 (external reviewer via operator dispatcher): `files_touched_expected` doesn't weight by file size
- module_04 (external reviewer via operator dispatcher): companion time budget is soft; adapter runs unbounded, no interrupt signal
- module_05 (external reviewer via operator dispatcher): Investigator lex-fallback biasable via `z_` file-rename attack
- module_05 (external reviewer via operator dispatcher): sycophancy classifier moderate-high FN rate on indirect/euphemistic reversals
- module_05 (external reviewer via operator dispatcher): `scan_trace` reports only closest reversal per anchor; distinct chains under-reported
- module_05 (external reviewer via operator dispatcher): narrow `load_sidecar_alm_pubkey` catch to `JSONDecodeError` + `binascii.Error`
- module_06 (cross-family reviewer via operator dispatcher): rule-like detector under-inclusive on wrapper phrasings (invariant/uniqueness)
- module_06 (cross-family reviewer via operator dispatcher): low-confidence branch always runs `rename_entities`; needs randomization
- module_06 (cross-family reviewer via operator dispatcher): case-mapping subtlety in reverse rename (latent hole)
- module_06 (cross-family reviewer via operator dispatcher): AST canonicalizer for semantic control-flow equivalence (astor)
- module_06 (cross-family reviewer via operator dispatcher): pre-transform anomaly check on free-var count vs token count
- module_07 (external reviewer via operator dispatcher): `crash_rate` companion column alongside `attested_pass_rate`
- module_07 (external reviewer via operator dispatcher): `attestation_gap` 0.05/0.20 thresholds need empirical calibration across ≥3 providers
- module_07 (external reviewer via operator dispatcher): `MISSING_ROOTKNOT.txt` whitespace-split parsing breaks on names with spaces

## Operator-side dispatcher gaps

Four reviewer-drift events surfaced across the ALM pipeline where the
module's plan named a specific reviewer endpoint that was not actually
available at dispatch time. In each case the pipeline fell back to a
cross-family alternative and the Second Pass still shipped, but the
operator's dispatcher-scoping documentation is systematically not what
actually ships. The RACT repo tree cannot write to the operator's
dispatcher-scoping documentation per the executor fence; these items are
recorded here for the operator to resolve outside the RACT tree.

- **module_02 reviewer-not-in-catalog:** plan named an OpenRouter DeepSeek-family reviewer function that the operator's dispatcher catalog did not expose. Fell back to a cross-family reviewer endpoint. Resolution: either restore the named reviewer in the operator's local multi-provider dispatcher OR update the operator's dispatcher-scoping documentation to remove it.
- **module_04 Google-quota-exhausted:** plan named a Google reasoning reviewer; daily free-tier quota (20 requests) was already exhausted at dispatch time. Fell back to a cross-family NVIDIA reviewer. Resolution: either raise the Google free-tier quota OR update the operator's dispatcher-scoping documentation to reflect the 20/day ceiling.
- **module_05 Mistral-budget-exhausted:** plan named a Mistral reviewer for a third-family review of the sacred-spine change; daily token budget was at 28164/30000 and the module_05 prompt was ~31000 tokens. Fell back to a Google cross-family reviewer. Resolution: raise Mistral daily token budget OR update the operator's dispatcher-scoping documentation to reflect the 30k/day token ceiling.
- **module_06 reviewer-not-in-catalog (repeat of module_02 event):** plan named the same DeepSeek-family reviewer again; same fallback path to the cross-family reviewer as module_02. This is the fourth reviewer-drift event on eight modules attempted.

## v0.5 hardening (from module_08 second pass)

Module_08's Second Pass surfaced ONE CONCRETE DEFECT (VERSION-vs-tag
identity check inadequate; fixed in commit `9a0b684`) and TRUNCATED
BEFORE ANSWERING Q1/Q2/Q4. The following items feed the v0.5 backlog:

- **v0.4.0-final second-pass re-coverage.** Q1 (43-signal distinctness), Q2 (CHANGELOG completeness vs 14 ADRs), and Q4 (ROADMAP compilation completeness) went unanswered because the external reviewer response truncated at ~1.2 KB. Self-audit substituted, but a follow-up dispatch (four sequential lightweight prompts) is queued for the v0.4.0-final review cycle so the reviewer's own distinctness/completeness/compilation claims are on the record.
- **Mistral daily token budget vs single-prompt reasoning size.** ALM modules 05 and 08 both fell back from the Mistral reasoning reviewer because the daily token budget (30 000) is smaller than a single reasoning prompt (typically ≥30 000 tokens). Feed into the operator's dispatcher-scoping documentation: either raise the Mistral tier before v0.4.0-final OR remove the Mistral reasoning reviewer from the ALM scoping recommendations.
- **Dispatcher `finish_reason: length` surfacing.** Each provider dispatcher module in the operator's local multi-provider dispatcher should surface `finish_reason: length` warnings so a truncated review is visible to the caller rather than silent. Queued for the operator side.
- **Version-string spelling unification.** VERSION carries the hyphenated `v0.4.0-rc1` display form; `pyproject.toml` and `__init__.py` carry the PEP 440 canonical `0.4.0rc1`; the two are the same version identity under `packaging.version.Version`, but a v0.5 cleanup could unify to a single spelling everywhere and add a lint enforcing the choice.

## v0.5 hardening (from retroactive audit)

The 2026-07-27 Retroactive Endpoints Audit dispatched the five v0.4.0-rc1
decisions that had not gone through the two-endpoint review discipline
during the pipeline. D1 and D6 landed release-surface fixes; the
following items feed the v0.5 backlog as deeper improvements:

- **Endpoints-SKILL scoping table drift.** D12 (Google reasoning-reviewer
  meta-review of the Second Pass discipline) surfaced that the
  plan-named reviewer pair for modules 02 and 06 was a DeepSeek-family
  OpenRouter reviewer against an NVIDIA DeepSeek-family reviewer — both
  same family. That is same-family, not cross-family, contrary to the
  discipline's stated blind-spot-diversity goal. The fallback reviewer
  actually used was MORE cross-family than the plan named. Revise the
  operator's dispatcher-scoping documentation so producer-reviewer
  pairs are cross-family by construction, not by accident.
- **Second-Pass reviewer reliability profile.** D12 also flagged that
  the external reviewer truncated at ~1.2 KB on the module_08 release-
  close review despite `--max-tokens 8000`. When response-size
  reliability matters (release-close reviews), plan-time endpoint
  choice should account for observed truncation patterns, not just
  family diversity. Add a `reliability_notes` column to the
  operator-side scoping table listing known truncation events per
  endpoint.
- **Executor-held helper enumeration.** D6 landed the fix for four
  helpers (`LoadBearingGuard`, `DuplicationGuard`, `NoveltyBudget`,
  `CompressionNoveltyDetector`) via an explicit `_HELPER_ATTRS` tuple
  in `substrate_adapter.py`. A v0.5 hardening item is to invert this:
  add a discoverable protocol (`ExecutorHelperWithProjectDir`) so any
  new helper the Executor accepts automatically joins the rebind set
  without a manual edit. The current test pins the enumeration; the
  protocol would remove the manual step.

## v0.5 hardening (from functionality audit)

Landed alongside the retroactive-audit sweep on 2026-07-27. One
concrete-defect fix commit (`249c0c7`) covers the CLI verb gap; the
remaining items below are usability polish surfaced by the six-lens
audit and Lens 3's cross-family first-user simulation.

- **Unify first-run prerequisites across install paths.** Lens 3
  reviewer noted that `pip install ract`, the source install, and the
  in-source editable path all name different prerequisites in
  different sections. Consolidate into a single "Before you install"
  block in README + QUICKSTART that lists Python 3.11+, git repo
  (implicit for the substrate loop), and provider env vars in one
  place.
- **Success-output examples for the first `ract` run.** Lens 3
  reviewer flagged "no clear expectation on what success looks like."
  Add a fenced code block after the Quickstart's first `ract "…"`
  showing the expected tail of the run (report path, exit code,
  where `evals/runs/<run_id>/` lands).
- **Post-first-run linear onboarding.** Lens 3 rated the jump from
  first-run to sessions/project-docs/modes as "information overload."
  Add a "What's next" ladder that walks a new user through: (a) run
  once, (b) inspect the report, (c) resume via `--session`, (d)
  advanced modes. Today all four appear at the same nesting depth.
- **Copy-paste-verbatim README lint.** The `ract run "…"` line ran
  verbatim from README failed on rc1 until fix commit `249c0c7`
  (missing `run` alias). Cold Lens 3 reviewers do not always simulate
  copy-paste execution, so add an in-repo lint that extracts every
  fenced `ract …` command from README.md + docs/QUICKSTART.md and
  runs it (or its `--help` when it would spend budget) as part of the
  test suite. Would have caught the defect without a first-user
  report.

## v0.5 hardening (from intent-fidelity module_01)

- `intent-fidelity module_01`: fence coverage across every deletion path
  not audited (systematic grep + audit of `os.unlink` / `shutil.rmtree`
  / `Path.unlink` / `remove` call sites against the FenceGate
  `consume_ticket` invariant); log each unguarded path as fix or
  intentional exception.
- `intent-fidelity module_01`: per-verb stub-detection fixture harness
  not automated (standing test suite that instantiates every CLI verb
  in `CLI_VERBS` against a fixture workspace and asserts each returns
  something a `pass` stub cannot produce).
- `intent-fidelity module_01`: automated CLI-surface diff across every
  tag not implemented (CI check that diffs `CLI_VERBS` across every tag
  would catch silent renames the first commit they land).

## v0.5 hardening (from intent-fidelity module_02)

- `intent-fidelity module_02`: `verify_workspace` not wired into the
  loop entry (`check_t3(state.provenance_ok)` reads a boolean no code
  path sets; substrate-era design decision pending — wire per-step
  provenance evaluation, or remove the dead path). Cross-references
  `intent-fidelity module_04` gap 5.
- `intent-fidelity module_02`: provider router selection does not
  consult health (integrate a health filter into selection, subsume
  under conformance report, or explicitly retire the v0.2 aspiration).
  Cross-references `intent-fidelity module_04` scope.
- `intent-fidelity module_02`: RK-3-extended-field property-test corpus
  for RK-1/RK-2 coverage — v2/v3 parametrizations that construct
  extended knots with corrupted RK-1 fields and assert those specific
  violations fire.

## v0.5 hardening (from intent-fidelity module_03)

- `intent-fidelity module_03`: benchmark report's 80% delta was
  measured against the v0.3 milestone-driven loop; re-run
  `evals/benchmarks/refactor-token-usage/report.py` under the v0.4
  substrate loop and either refresh the report or add a v0.4-specific
  benchmark task. Cross-references `intent-fidelity module_04` gap 4.
- `intent-fidelity module_03`: `docs/PROVENANCE.md` is at the 800-word
  independence-lint cap after fix `fdd7474`; raise cap or split
  sidecar-schema table into a companion doc before any future
  attestation-era addition.

## v0.5 hardening (from intent-fidelity module_04)

Root cause: the executor-adapter shim at
`src/ract/executor/substrate_adapter.py:206-214` constructs
`SubstrateLoop` without `CapabilityManifest`, `SandboxBackend`, or
`JsonlEventWriter`. All four SUBSTRATE PARTIAL signals plus the ten
ALM PARTIAL signals share this root. Cross-references
`v0.5 hardening (from substrate close)` lines 73-74.

- `intent-fidelity module_04` gap 1: signals 4 + 5 shim upgrade
  (manifest + OS-enforced sandbox on the SubstrateLoop the shim
  constructs; run-id + workspace-root propagation for per-run manifest
  publication).
- `intent-fidelity module_04` gap 2: signal 9 event-log wiring
  (`JsonlEventWriter` constructed and registered by the runtime for
  every real run; `<run_dir>/events.jsonl` non-empty and hash-chained).
- `intent-fidelity module_04` gap 3: signal 10 OTLP smoke test with a
  local collector fixture.
- `intent-fidelity module_04` gap 5: SUBSTRATE-era `check_t3`
  dead-code path — design decision pending between wiring per-step
  provenance evaluation (T3 reachable) and removing `check_t3` +
  `provenance_ok` from the enum. Cross-references
  `intent-fidelity module_02` gap 1.
- `intent-fidelity module_04` gap 6: executor legacy-path fence
  bypass on shell / diff_applier deletions (signal 15 partial in
  shim path; propagate deletions as `DeleteFileAction` objects OR add
  a Fence hook to `diff_applier.apply_diff` and the shell tool).

## v0.5 hardening (from intent-fidelity module_05)

- `intent-fidelity module_05` gap 1: ALM signals 1-10 + 16 shim wiring
  — folds under `intent-fidelity module_04` gap 1-3; when the shim
  upgrade lands, call `write_mutation_report` / `write_coverage_report`
  / `run_completion_gates` from the runtime path.
- `intent-fidelity module_05` gap 2: sycophancy circuit not wired to
  `LoopController` (signal 9; two-line integration when event log is
  wired). Cross-references `docs/ROADMAP.md:101`.
- `intent-fidelity module_05` gap 3: Investigator required-input
  coupling not enforced at G6 + G7 (signal 10; extend `enforce_g6` to
  accept optional `investigator_report` and raise
  `LazinessViolatedError` on absence when under-edit-closure names
  untouched files).
- `intent-fidelity module_05` gap 4: `COMPANION_MATRIX` enforcement is
  name-substring, not family-substring (signal 15 hardening; extend
  `enforce_different_provider` with a `family_of` callable). Cross-
  references `docs/ROADMAP.md:132`.
- `intent-fidelity module_05` gap 5: module_05 spec text drift (three
  vs four AL-1 sub-clauses; matrix enforcement locus; signal-5
  "sandbox layer" naming) — either update spec text to name shipped
  surfaces exactly or land an ADR-note that spec text is aspirational.
- `intent-fidelity module_05` gap 6: AL-1 fourth all-vary property
  test (Second Pass Q5) — non-blocking; ordering guarantee is a
  design property beyond sub-clause-independence invariant.

## v0.5 hardening (from intent-fidelity module_06)

Gaps 1-4 forwarded from `intent-fidelity module_05` unchanged (this
module is v0.4.0-rc1 audits era, not the code-wiring era).

- `intent-fidelity module_06` gap 7: wordlist-growth review cadence
  (Second Pass Q1) — extend `_CLOSED_IP_TERMS` on operator confirmation
  of a growth manifest; add a standing pre-release-tag review that
  greps operator-side private-name registries against the wordlist for
  candidate additions.
- `intent-fidelity module_06` gap 8: helper-enumeration introspection
  (Second Pass Q2) — replace hand-maintained `_HELPER_ATTRS` with a
  marker Protocol (`ProjectAnchoredHelper`) helpers explicitly
  implement; auto-detect on init.

## v0.5 hardening (from intent-fidelity module_07)

Gaps 1-8 forwarded from `intent-fidelity modules 05 and 06` unchanged
(module_07 is restoration-cluster verification, not the code-wiring
era). Native gaps:

- `intent-fidelity module_07` gap 9: `MISSING` sentinel consumer
  migration — primitive holds and is production-ready, but no consumer
  site in `src/ract/` currently has the None-vs-unpassed ambiguity the
  sentinel is designed to disambiguate. Adoption triggered by new-
  surface need, not by mass-migration of existing callsites.
- `intent-fidelity module_07` gap 11: `demo.cast` freshness gate has a
  signature-change loophole (verb-name-only regex; an argument-signature
  change to an existing verb that keeps the verb name would not flip
  the gate). Extend to hash each `ract <verb> ...` invocation's full
  argv against the current argparse subparser choices.

## Previously logged (pre-v0.4) — carried forward

Items from the pre-v0.4 roadmap that remain open:

- **Public leaderboard backend** — accept and compare signed receipts from users who opt in.
- **VS Code extension** — surface loop status, handshakes, and receipts inside the editor.
- **Benchmark results** — compare RACT against Cursor/Claude Code on code-quality metrics.
- **Community channel** — Discord or Slack for early adopters.
- **Animated asciicast/GIF** — blocked until a terminal recorder supports Windows ARM64.
- **CLA assistant** — blocked at the OAuth handshake step; the setup URL is open.

<!-- RACT 0.4.1 -->
