# RACT Roadmap

Post-release upgrade queue. v0.4.0-rc1 (2026-07-26) closes the SUBSTRATE
and Anti-Lazy Module (ALM) pipelines with the environment as thorough
verifier; this file compiles the honest-gaps log from every one of the
fourteen combined-pipeline modules plus every deferred deeper-improvement
finding from the ALM Second Passes plus four dispatcher-drift events at
the operator-side endpoints_SKILL boundary.

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
- module_05: `endpoints_SKILL.md` three-family review example not landed (see operator-side gaps below)
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

- module_01 (Google flash_reason): ACH 0.79 precision inflates `kill_rate` denominator; ~21% missed equivalents
- module_01 (Google flash_reason): trivial-holdout ceiling insufficient — add compose-time signal + consecutive-similar refusal
- module_02 (OpenRouter Nemotron Ultra): `_classify_triviality` gameable by mixed-diff (formatter + substantive)
- module_02 (OpenRouter Nemotron Ultra): 3-run flakiness filter 52% pass at 20% flake; need adaptive N + Wilson interval
- module_03 (Google flash_reason): data-flow escape via `s = pytest.skip; s()` bound-method assignment
- module_03 (Google flash_reason): handshake-approval per-pattern cap absent (`max_handshake_approvals_per_pattern`)
- module_03 (Google flash_reason): no cross-run cluster analysis over `handshake.requested`/`resolved`
- module_03 (Google flash_reason): `SymbolNode` lacks signature info; arg-list/return changes miss under-edit
- module_03 (Google flash_reason): full tree-sitter analyzers for TypeScript/Go/Rust G5/G6
- module_04 (NVIDIA reason_deep): companion-matrix vs live conformance staleness (no per-schedule liveness check)
- module_04 (NVIDIA reason_deep): `files_touched_expected` doesn't weight by file size
- module_04 (NVIDIA reason_deep): companion time budget is soft; adapter runs unbounded, no interrupt signal
- module_05 (Google flash_reason): Investigator lex-fallback biasable via `z_` file-rename attack
- module_05 (Google flash_reason): sycophancy classifier moderate-high FN rate on indirect/euphemistic reversals
- module_05 (Google flash_reason): `scan_trace` reports only closest reversal per anchor; distinct chains under-reported
- module_05 (Google flash_reason): narrow `load_sidecar_alm_pubkey` catch to `JSONDecodeError` + `binascii.Error`
- module_06 (OpenRouter Nemotron Ultra): rule-like detector under-inclusive on wrapper phrasings (invariant/uniqueness)
- module_06 (OpenRouter Nemotron Ultra): low-confidence branch always runs `rename_entities`; needs randomization
- module_06 (OpenRouter Nemotron Ultra): case-mapping subtlety in reverse rename (latent hole)
- module_06 (OpenRouter Nemotron Ultra): AST canonicalizer for semantic control-flow equivalence (astor)
- module_06 (OpenRouter Nemotron Ultra): pre-transform anomaly check on free-var count vs token count
- module_07 (Google flash_lite): `crash_rate` companion column alongside `attested_pass_rate`
- module_07 (Google flash_lite): `attestation_gap` 0.05/0.20 thresholds need empirical calibration across ≥3 providers
- module_07 (Google flash_lite): `MISSING_ROOTKNOT.txt` whitespace-split parsing breaks on names with spaces

## Operator-side dispatcher gaps

Four reviewer-drift events surfaced across the ALM pipeline where the
module's plan named a specific reviewer endpoint that was not actually
available at dispatch time. In each case the pipeline fell back to a
cross-family alternative and the Second Pass still shipped, but the
`endpoints_SKILL.md` scoping recommendations are systematically not what
actually ships. The RACT repo tree cannot write to the operator's
`endpoints_SKILL.md` per the executor fence; these items are
recorded here for the operator to resolve outside the RACT tree.

- **module_02 R1-not-in-catalog:** plan named OpenRouter `reason_r1_latest` (DeepSeek R1); OpenRouter dispatcher catalog does not expose that function. Fell back to `reason_nemotron_ultra` (Nemotron 3 Ultra 550B). Resolution: either restore `reason_r1_latest` in `openrouter_dispatch.py` OR update `endpoints_SKILL.md` scoping recommendations to remove `reason_r1_latest`.
- **module_04 Google-quota-exhausted:** plan named Google `flash_reason`; daily free-tier quota (20 requests) was already exhausted at dispatch time. Fell back to NVIDIA `reason_deep`. Resolution: either raise the Google free-tier quota OR update `endpoints_SKILL.md` scoping to reflect the 20/day ceiling.
- **module_05 Mistral-budget-exhausted:** plan named Mistral `reason_magistral` for a third-family review of the sacred-spine change; daily token budget was at 28164/30000 and the module_05 prompt was ~31000 tokens. Fell back to Google `flash_reason` (cross-family). Resolution: raise Mistral daily token budget OR update `endpoints_SKILL.md` to reflect the 30k/day token ceiling.
- **module_06 R1-not-in-catalog (repeat of module_02 event):** plan named `reason_r1_latest` again; same fallback path to `reason_nemotron_ultra` as module_02. This is the fourth reviewer-drift event on eight modules attempted.

## v0.5 hardening (from module_08 second pass)

Module_08's Second Pass surfaced ONE CONCRETE DEFECT (VERSION-vs-tag
identity check inadequate; fixed in commit `9a0b684`) and TRUNCATED
BEFORE ANSWERING Q1/Q2/Q4. The following items feed the v0.5 backlog:

- **v0.4.0-final second-pass re-coverage.** Q1 (43-signal distinctness), Q2 (CHANGELOG completeness vs 14 ADRs), and Q4 (ROADMAP compilation completeness) went unanswered because the Google flash_reason response truncated at ~1.2 KB. Self-audit substituted, but a follow-up dispatch (four sequential lightweight prompts) is queued for the v0.4.0-final review cycle so the reviewer's own distinctness/completeness/compilation claims are on the record.
- **Mistral daily token budget vs single-prompt reasoning size.** ALM modules 05 and 08 both fell back from Mistral `reason_magistral` because the daily token budget (30 000) is smaller than a single reasoning prompt (typically ≥30 000 tokens). Feed into the operator-side endpoints_SKILL scoping table: either raise the Mistral tier before v0.4.0-final OR remove `reason_magistral` from the ALM scoping recommendations.
- **Dispatcher `finish_reason: length` surfacing.** Each provider dispatcher (`google_dispatch.py`, `nvidia_dispatch.py`, `openrouter_dispatch.py`, `mistral_dispatch.py`) should surface `finish_reason: length` warnings so a truncated review is visible to the caller rather than silent. Queued for the operator side.
- **Version-string spelling unification.** VERSION carries the hyphenated `v0.4.0-rc1` display form; `pyproject.toml` and `__init__.py` carry the PEP 440 canonical `0.4.0rc1`; the two are the same version identity under `packaging.version.Version`, but a v0.5 cleanup could unify to a single spelling everywhere and add a lint enforcing the choice.

## v0.5 hardening (from retroactive audit)

The 2026-07-27 Retroactive Endpoints Audit dispatched the five v0.4.0-rc1
decisions that had not gone through the two-endpoint review discipline
during the pipeline. D1 and D6 landed release-surface fixes; the
following items feed the v0.5 backlog as deeper improvements:

- **Endpoints-SKILL scoping table drift.** D12 (Google flash_reason
  meta-review of the Second Pass discipline) surfaced that the
  plan-named reviewer pair for modules 02 and 06 was OpenRouter
  `reason_r1_latest` against NVIDIA `reason_deep` — both DeepSeek
  family. That is same-family, not cross-family, contrary to the
  discipline's stated blind-spot-diversity goal. The Nemotron fallback
  was actually MORE cross-family than the plan named. Revise the
  operator-side `endpoints_SKILL.md` scoping table so
  producer-reviewer pairs are cross-family by construction, not by
  accident.
- **Second-Pass reviewer reliability profile.** D12 also flagged that
  Google `flash_reason` truncated at ~1.2 KB on the module_08 release-
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

## Previously logged (pre-v0.4) — carried forward

Items from the pre-v0.4 roadmap that remain open:

- **Public leaderboard backend** — accept and compare signed receipts from users who opt in.
- **VS Code extension** — surface loop status, handshakes, and receipts inside the editor.
- **Benchmark results** — compare RACT against Cursor/Claude Code on code-quality metrics.
- **Community channel** — Discord or Slack for early adopters.
- **Animated asciicast/GIF** — blocked until a terminal recorder supports Windows ARM64.
- **CLA assistant** — blocked at the OAuth handshake step; the setup URL is open.

<!-- RACT 0.4.0-rc1 -->
