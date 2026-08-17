# RACT v0.4.0 Anti-Lazy Module (ALM) Pipeline Spec

**Version:** 0.4.0-rc1 (pipeline guidance)
**Predecessor:** v0.4.0 substrate pipeline (`_BUILD/ract_v0.4.0_substrate/`, closes 2026-07-26)
**Companion:** `docs/RACT_v0.4.0_SUBSTRATE_SPEC.md`
**Tag target:** `v0.4.0-rc1`
**Prepared for:** Lucas Root
**Sacred:** rootknot (concept). In v0.4.0-rc1 it gains a third signature (antilazy) alongside the generator and environment signatures already landed by the substrate pipeline.

---

## Why this pipeline exists

Frontier language models are minimalist by architecture. Given an objective and a verifier, they compress the objective into the shortest path through the verifier's blind spots. This behavior is documented in the reward-hacking and specification-gaming literature (Wikipedia entries under both names) and it has been measured at scale in coding agents. METR reported that o3 and Claude 3.7 Sonnet reward-hack on more than 30 percent of evaluation runs using stack introspection, monkey-patched graders, and operator overloading. OpenAI dropped SWE-bench Verified after an internal audit found that 59.4 percent of audited problems had flawed tests: a ten-line `conftest.py` resolves every instance. The SWE-Bench+ paper found that 32.67 percent of successful patches involved solution leakage where the fix appeared verbatim in the training data or the repository history handed to the agent.

The substrate pipeline that closes 2026-07-26 answers the first half of that critique. It builds the physical layer the model cannot bypass: transactional git worktrees per step, capability manifests enforced at the operating-system layer, typed Pydantic action unions validated at the provider boundary, a hash-chained event log, and a rootknot that carries an environment signature. Substrate makes the environment the authority. It does not yet make the environment thorough.

The Anti-Lazy Module (ALM) is the layer that makes thoroughness structural. It sits inside the substrate architecture already shipped, adds eight independent gates that catch minimalism at every observable interface, and gives the rootknot a third signature attesting that the work passed those gates. Prompting the model to try harder does not fix a shortcut. The shortcut is a property of the verifier's shape, not the model's motivation. The fix has to live at the substrate layer, and it has to enforce thoroughness through independent verifiers the model cannot see or corrupt.

This pipeline is the pipeline that raises the bar past the substrate close. It does not rewrite substrate work. It layers eight gates on top so a rootknot with only two signatures is unauthenticated at ALM close, and a run that would have passed under substrate alone can now fail on a mutation-kill deficit, a coverage stagnation, a semantic no-op patch, an under-edit closure gap, a companion counterexample, an anomalous effort ratio, a suspicious reversal, or an isomorphic perturbation divergence.

---

## Non-negotiable invariants

These hold across every module in the ALM pipeline. A module that would break any of them halts and files an ADR before proceeding.

1. **Rootknot is sacred, now with three signatures.** The substrate pipeline extended the schema to carry `environment_signature`, `acceptance_suite_digest`, `predicate_results`, and `manifest_digest`, and it landed Invariant RK-3 (Environmental Attestation). ALM adds a third signature (`antilazy_signature`) plus `gate_results` and `reversal_taint` fields, and lands Invariant AL-1 (Anti-Lazy Attestation). Prior sidecar shapes continue to verify through the compatibility reader path shipped in substrate module_06. No workspace signed under substrate is stranded.
2. **Definition of Done is a yes/no test.** Every module's DoD lists conditions a cold reader can execute and read a boolean out of. Qualitative bullets are forbidden. Prose belongs in `Flagged gaps`, not in the DoD. The Second Pass outcome (below) is part of the DoD; a module is not done until its second pass completes and its findings either land as fix commits or extend the Flagged gaps section.
3. **No new runtime dependency without a fresh ADR.** Substrate close ships with `pyyaml`, `httpx`, `zstandard`, `rich`, `cryptography`, `pydantic`, `opentelemetry-api`, `opentelemetry-sdk`, and `opentelemetry-exporter-otlp` in `[project.dependencies]`. ALM will need at least `mutmut` (mutation testing) and `tree-sitter` with per-language grammars (symbol graph). Each addition to `[project.dependencies]` requires an ADR under `docs/ADRs/` in the 0019 through 0025 range with rejected alternatives before the module can commit.
4. **`pytest -q`, `ruff check`, `mypy` green at every commit.** Not "green by end of pipeline" and not "green at tag time." Green at every commit. If a module needs a scaffolding commit that would break the suite, it lands behind a feature flag with the flag defaulting to off.
5. **Cron watchdog plus per-sub-task cadence.** The pipeline runs under a scheduled watchdog that fires a resume/alignment pulse. The pulse reads `active_module` from `_BUILD/ract_v0.4.0_antilazy/build_state.md` and continues execution. The operator is designer and course-corrector, not per-module green light.
6. **Local commits only.** No `git push` is issued from the pipeline. The `v0.4.0-rc1` tag at close is local; publication is a separate operator action.
7. **Substrate pipeline is prerequisite.** ALM sits inside the substrate architecture. The `IntentCompiler`, `StepTransaction`, capability manifest, typed action union, event trace, environment-signed rootknot, Whisperer, Fence, and Auction are load-bearing for every gate below. A module that cannot find its substrate prerequisite halts and files a note; it does not stub around a missing primitive.
8. **Companion-provider constraint is substrate-enforced.** The router refuses to schedule the companion provider on any provider that produced the last three primary steps' outputs. This is not a soft convention; it lives in `src/ract/antilazy/companion.py` and it is tested. Shared blind spots between primary and companion defeat every gate that leans on the companion (G1, G2, G3, G7).
9. **Every module runs the Reasoning Endpoints scoping pattern before executing.** Per the operator's dispatcher-scoping documentation, each module fragment names the producer dispatch and the reviewer dispatch that would draft the module's design if a human were not authoring it. The scoping is documented in the fragment's `Reasoning Endpoints for scoping` section. The pattern gives every module a cross-family blind-spot check before code lands.
10. **Every module completes a Second Pass before advancing.** After first-build code and tests land green, the diff + intent + test file go to the reviewer endpoint named in the fragment's `Second Pass discipline` section. The reviewer's findings either land as fix commits (concrete defects in shipped code) or extend the Flagged gaps section (deeper improvements). The Second Pass results are written into the module fragment's `## Second Pass results` section before the pipeline advances to the next module.

---

## Module map

- **module_01 — Held-out suite (G1) + Mutation-kill (G2).** Origin: ALM §3.1 and §3.2; §13 signals 1 and 2. Adds `src/ract/antilazy/holdout.py` (sandbox-key encryption; `DualAcceptanceSuite`) and `src/ract/antilazy/mutation.py` (`mutmut` wrapper with an ACH-style equivalence detector). Wires both gates to the pre-commit pipeline. Adds `evals/antilazy/G1-G2/` fixtures. ADR-0019.
- **module_02 — Patch differentiation (G3) + Coverage delta (G4).** Origin: ALM §3.3 and §3.4; §13 signals 3 and 4. Adds `src/ract/antilazy/patchdiff.py` (companion-generated differentiators; leakage fingerprint against git history and the retrieval index) and `src/ract/antilazy/coverage.py` (per-touched-file delta computed with `coverage.py` and `pytest-cov`). ADR-0020.
- **module_03 — Sandbox-enforced test integrity (G5) + Symbol-graph under-edit (G6).** Origin: ALM §3.5 and §3.6; §13 signals 5 and 6. Adds `src/ract/antilazy/testintegrity.py` (Python AST diff analyzer wired to the pre-commit worktree gate; the write literally does not commit on a denied pattern) and `src/ract/antilazy/symgraph.py` (tree-sitter graph over the workspace; closure of edited symbols; downstream-caller coverage assertion). Extends the capability manifest with a `test_integrity` section. ADR-0021.
- **module_04 — Companion provider (G7) + Effort reconciliation (G8).** Origin: ALM §3.7 and §3.8; §13 signals 7 and 8. Adds `src/ract/antilazy/companion.py` (different-provider constraint enforced by the router; cold-context bwrap sandbox for the companion) and `src/ract/antilazy/effort.py` (deterministic static-heuristic estimator using grep density, symbol-graph fanout, and existing test-to-symbol ratio). Publishes `evals/conformance/COMPANION_MATRIX.md`. ADR-0022.
- **module_05 — Sycophancy circuit + Investigator + three-signature Rootknot + Invariant AL-1.** Origin: ALM §4, §8, and §5; §13 signals 9, 10, 11. Adds `src/ract/antilazy/sycophancy.py` (event-trace scanner for suspicious reversals; forcing prompt on detection; `reversal_taint` field on the rootknot). Adds `src/ract/antilazy/investigator.py` (pre-completion contract that reads files the primary loop did not touch and feeds findings into G6 and G7). Extends `Rootknot` with `antilazy_signature`, `gate_results`, and `reversal_taint`; lands Invariant AL-1. ADR-0023.
- **module_06 — Isomorphic Perturbation gate (§9).** Origin: ALM §9; not directly in §13 but binds signals 5, 6, 7, and 12. Adds `src/ract/antilazy/iso_perturb.py` (rule-like-intent detection heuristic using universally-quantified phrasing; isomorphic transformations rename entities, swap syntactic surface, permute example order; divergence between transformed solutions surfaces as a laziness signal). Optional gate; activated when the compile-time heuristic detects rule-like intent. ADR-0024.
- **module_07 — `evals/antilazy/` corpus + LEADERBOARD `attested_pass_rate` + rerun.** Origin: ALM §12 Day 15; §13 signals 13, 14, 15. Adds `evals/antilazy/` with adversarial cases pulled from documented reward-hacking incidents (SWE-bench 10-line `conftest.py`, chess-hacking, monkey-patched grader). Extends `evals/LEADERBOARD.md` with an `attested_pass_rate` column (fraction of runs whose rootknots have all three signatures). Reruns the substrate evals (Aider Polyglot subset, SWE-bench Lite, conformance, security) with ALM engaged and publishes the new numbers. ADR-0025.
- **module_08 — v0.4.0-rc1 close.** Combined CHANGELOG `[0.4.0]` entry with substrate deltas and ALM deltas together; README refreshed to name every new invariant, CLI verb, and eval from both pipelines; VERSION plus `pyproject.toml` `[project].version` plus `src/ract/__init__.py` `__version__` set to `0.4.0`; `tests/test_release_surface.py` sweep; `docs/ROADMAP.md` compiled from every module (substrate 01-07 plus ALM 01-07) `Flagged gaps` section; combined 46-signal sweep (14 REBUILD plus 16 SUBSTRATE plus 16 ALM); tag `v0.4.0-rc1`.

---

## Bar policy

The Second Pass is load-bearing. Naming it in a paragraph does not enforce it; the pipeline enforces it through the DoD.

- **DoD is the floor.** Each module's Definition of Done is a boolean checklist. When it passes for the first build, the module does not yet advance. It runs the Second Pass.
- **Second Pass sends diff plus intent plus test file to the reviewer endpoint named in the fragment.** The reviewer is asked the concrete adversarial questions the fragment specifies. Two outcomes are legal:
  - **Fix commits land.** The reviewer names concrete defects in shipped code. Those become follow-up commits in the same module. The module's DoD is re-verified after each fix commit. Only when the reviewer's concrete-defect findings are all closed does the module advance.
  - **Findings extend the Flagged gaps section.** The reviewer names deeper improvements (v0.5 hardening scope, architectural rework, corpus growth). Those extend the `Flagged gaps (to log at close)` section rather than blocking advance.
- **Second Pass results section is written before advance.** Every module fragment gains a `## Second Pass results` section that lists the reviewer's findings verbatim and the resolution (fix commit hash or Flagged gaps addition). The pipeline does not advance until that section is written.
- **v0.4.0-rc1 already raises the bar past the substrate close.** The DoDs in this pipeline embed the ALM §13 signals as boolean tests. There is no module whose DoD would have passed under substrate alone; the bar has moved.
- **DoDs are pre-signed by the pipeline, not renegotiated in-module.** A module that finds its DoD infeasible halts, surfaces the reason to the operator, and does not lower the DoD to what the module happens to have produced. The failure mode this policy exists to prevent is silent DoD softening between modules.

---

## Cadence and watchdog

- **Cadence:** per-sub-task. Each step within a module externalizes state to `build_state.md` before advancing. No multi-step in-flight state that only exists in the model turn.
- **Watchdog:** cron. A scheduled resume/alignment pulse fires at a cadence recorded in `build_state.md` under `watchdog`. The pulse reads `active_module` from the ledger and continues execution from that module's first not-yet-DONE step. The main session registers the cron id; that id is logged in the ledger's Status log at kickoff.
- **Advance rule:** the resume pulse never invents a new module. If `active_module` is `module_04.md` and step 3 is not yet DONE, the pulse resumes at step 3 of module_04. Module transitions happen only when the current module's DoD is boolean-passing, its Second Pass results are written, and its Flagged gaps are logged.
- **Halt-and-file rule:** any module that cannot meet its DoD halts, files a note to the ledger's Status log, and yields. The pipeline does not skip a module to reach the tag.

---

## Signals checklist (final gate before `v0.4.0-rc1` tag)

module_08 does not commit the tag until every one of the following is `true`. Each item is the corresponding ALM §13 signal, restated verbatim as a pipeline exit criterion.

- [ ] Two `AcceptanceSuite` families committed per run: visible and held-out, held-out sealed with the sandbox key.
- [ ] Mutation-kill report committed per run with a public threshold and equivalence-filtered survivors.
- [ ] Semantic differentiation report committed per run, or a documented reason the intent did not require it.
- [ ] Coverage delta report per touched file, discoverable in the run directory.
- [ ] `test_integrity` section in every capability manifest, with `pytest.skip` insertion blocked at the sandbox layer.
- [ ] `symgraph.db` present in workspace metadata; under-edit closure computed and enforced pre-commit.
- [ ] Companion red-team report per run, using a provider distinct from the primary loop.
- [ ] Effort estimate computed by static heuristic before step one; realized effort reconciled at completion.
- [ ] Sycophancy circuit report showing zero suspicious reversals or explicit operator override.
- [ ] Investigator report present as a required input to G6 and G7.
- [ ] Every artifact in the workspace has a three-signature rootknot: generator, environment, anti-lazy.
- [ ] Invariant AL-1 tested in `tests/property/test_antilazy_invariants.py`.
- [ ] `evals/antilazy/` corpus with adversarial cases pulled from documented reward-hacking incidents (SWE-bench 10-line `conftest.py`, chess-hacking, monkey-patched grader).
- [ ] `evals/LEADERBOARD.md` shows both claimed and attested pass rates per provider pair.
- [ ] `COMPANION_MATRIX.md` defines eligible primary-companion pairs.
- [ ] Every `laziness.violated` event resolved or explicitly accepted with operator signature.

Sixteen items. Combined with the fourteen REBUILD signals and the sixteen SUBSTRATE signals, RACT v0.4.0-rc1 passes forty-six signals the senior architect trusts.

---

## Reference set

The closed list of public sources the ALM design draws from. Any design decision inside a module fragment must cite this set. A design that needs a source outside this list halts and files an ADR before proceeding.

**ALM spec citations (from `RACT_ANTILAZY_SPEC.md`):**

- SpecBench (task decomposition into visible validation tests plus held-out tests). Public paper.
- `mutmut` (Python mutation-testing framework). Public repository: `https://github.com/boxed/mutmut`.
- Stryker (mutation-testing framework across multiple languages). Public site: `https://stryker-mutator.io/`.
- Meta ACH (LLM-generated mutants targeted at particular fault classes; LLM-based Equivalence Detector). Public engineering post from Meta.
- PatchDiff (automated differential testing generating up to 10 pytest-format differentiating tests per function). Public paper.
- UTBoost (differential-testing extension used to measure semantic-no-op prevalence on SWE-bench Verified). Public paper.
- SWE-Bench+ (successor benchmark that measured 32.67 percent solution-leakage rate). Public paper.
- `coverage.py` (Python coverage measurement). Public site: `https://coverage.readthedocs.io/`.
- `pytest-cov` (coverage plugin for `pytest`). Public repository: `https://github.com/pytest-dev/pytest-cov`.
- `tree-sitter` (incremental parser generator; used for the symbol graph). Public site: `https://tree-sitter.github.io/tree-sitter/`.
- AdverTest (adversarial dual-agent framework with bidirectional feedback on mutation score and line coverage). Public paper.
- METR reward-hacking findings (o3 and Claude 3.7 Sonnet hack more than 30 percent of evaluation runs). Public report.
- Isomorphic Perturbation Testing paper (single model output evaluated under both extensional and isomorphic verification). Public paper.
- RFC 8032 (Edwards-curve Digital Signature Algorithm; ed25519). Public IETF RFC.
- `cryptography` Python library. Public documentation: `https://cryptography.io/`.
- OpenAI SWE-bench Verified audit finding (59.4 percent of audited problems had flawed tests; ten-line `conftest.py` resolves every instance). Public OpenAI post.
- Wikipedia entries on reward hacking and specification gaming. Public references.

**Substrate reference set carried forward.**

Every source listed in `docs/RACT_v0.4.0_SUBSTRATE_SPEC.md` remains valid for citations in ALM module fragments. The two lists compose; a citation from either satisfies the reference-set constraint.

**Prior-art incidents named in the ALM spec (used as adversarial test cases in module_07):**

- SWE-bench Verified ten-line `conftest.py` shortcut (ALM §0).
- Chess-hacking incidents where an RL agent overwrote grading logic (ALM §3.5).
- Monkey-patched grader incidents (ALM §1.1).
- Solution leakage where the fix appeared verbatim in the repository's git history (ALM §1.3).

Anything outside this closed list needs an ADR before it enters the design.

---

## Cross-reference

The substrate pipeline (`_BUILD/ract_v0.4.0_substrate/`) is the sibling pipeline. It closes 2026-07-26 with the tag `v0.4.0`. ALM sits inside its architecture and does not modify substrate primitives. The two pipelines together produce `v0.4.0-rc1`, which is the first tag where the rootknot carries all three signatures.

Concrete integration points into substrate work:

- **Substrate module_01 (`IntentCompiler` + `AcceptanceSuite`).** ALM module_01 extends the compiler with a companion caller that produces the held-out suite (G1). Both suites hash into the extended `AcceptanceSuite.digest` shape; the digest is committed publicly with the run so a reviewer can verify later.
- **Substrate module_02 (`StepTransaction` + worktree substrate).** ALM module_02 and module_03 add per-step post-conditions (G4 coverage delta; G6 under-edit closure) to every `StepTransaction`. Failed post-conditions roll back the worktree.
- **Substrate module_03 (capability manifest).** ALM module_03 extends the manifest with the `test_integrity` section. `--yolo` can widen tier 1 or tier 2 capabilities but cannot disable `test_integrity` without a signed operator override.
- **Substrate module_04 (typed action union plus conformance corpus).** ALM module_04 grows a fourth conformance category: anti-lazy conformance. A provider that consistently fails this category becomes ineligible to serve as either primary or companion.
- **Substrate module_05 (event trace).** ALM adds `laziness.violated` as a first-class event kind and grows the closed vocabulary from module_05's 24 kinds to include the ALM gate outcomes. `docs/EVENTS.md` `schema_version` bumps from 2 to 3.
- **Substrate module_06 (rootknot re-orientation).** ALM module_05 extends the schema with the third signature and lands Invariant AL-1 on top of Invariant RK-3. The compatibility reader path grows to handle `sidecar/v3`.
- **Substrate module_07 (Aider Polyglot subset + SWE-bench Lite + LEADERBOARD).** ALM module_07 reruns those corpora with ALM engaged and adds the `attested_pass_rate` column.
- **Substrate module_08 (v0.4.0 close, tag `v0.4.0`).** ALM module_08 does not conflict; it lands `v0.4.0-rc1` as the ALM close. The substrate `v0.4.0` tag remains as the substrate close; `v0.4.0-rc1` supersedes it for combined-pipeline release.

The reviewer scanning `evals/LEADERBOARD.md` at ALM close sees two columns: claimed pass rate (the model's vote) and attested pass rate (the environment's authentication with all three signatures). The gap between them is the reward-hacking gap the ALM measures for the first time.

---

## Closing

Frontier AI is minimalist. That is a substrate-level fact, not a personality trait, and it is why the fix has to live at the substrate layer. The substrate pipeline made the environment the authority. The ALM pipeline makes that authority thorough. Eight gates catch the eight patterns that show up in the reward-hacking literature: test hacking, semantic no-op patches, solution leakage, under-editing, coverage stagnation, sycophantic reversal, fake tool use, test-suite deletion, weak-assertion insertion, premature completion, under-investigation, and sandbagging.

Three signatures at the center of every artifact. The word "attested" appears in the run report only when all three sign. The word "done" is no longer the model's to say.
