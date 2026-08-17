# RACT v0.4.0 Substrate Rebuild Spec

**Version:** 0.4.0 (pipeline guidance)
**Predecessor:** v0.3.0 (tagged `v0.3.0`, 2026-07-25)
**Tag target:** `v0.4.0`
**Prepared for:** Lucas Root
**Sacred:** rootknot (concept). In v0.4 it attests **environmental verification**, not authorship.

---

## Why this pipeline exists

The v0.3.0 tag closed the REBUILD spec's craft agenda cleanly: repo hygiene, signed `Rootknot`, `AssumptionRegistry` with propagation, T1–T7 loop termination, tiered threat model, seven ADRs, a first eval harness. An audit against the two authoritative drafts under `docs/` — `RACT_REBUILD_SPEC.md` and `RACT_SUBSTRATE_SPEC.md` — showed the REBUILD signals essentially met (roughly 11 of 14 DONE, 3 PARTIAL), but the SUBSTRATE §11 signals sit at **14 of 16 MISSING** as of 2026-07-26:

- **DONE (1):** `__root_author__` scrubbed from `src/` and `tests/` (SUBSTRATE §11 signal 14).
- **PARTIAL (1):** Whisperer, Chesterton's Fence, and Dead Code Auction exist as CLI modules but not as in-loop environment-enforced contracts (SUBSTRATE §11 signal 15).
- **MISSING (14):** no compiled `AcceptanceSuite`, no transactional worktree/container execution, no capability manifest, no OS-enforced sandbox (bwrap plus Landlock plus seccomp on Linux, Seatbelt on macOS), no typed Pydantic action union, no conformance corpus gating router registration, no hash-chained event log, no OTLP export, no `ract trace replay|fork|diff|to-test`, no `environment_signature` on `Rootknot`, no Invariant RK-3, no `evals/LEADERBOARD.md` with Aider Polyglot subset and SWE-bench Lite pass rates.

The three biggest MVP-shaping gaps drive module priority:

1. **Transactional execution substrate.** Without git-worktree-per-step plus container-per-step, every other substrate move (capability manifest, event log, environment signature) has no ground to stand on. The workspace is not durable, so nothing signed against it is durable either. Module 02 lands this.
2. **Compiled acceptance predicates.** Without an externally verifiable suite frozen before the loop enters step one, loop termination is still a model judgment about model output. Module 01 lands this — before module 02, because module 02's rollback rule refers to a step's post-conditions and those post-conditions are `AcceptancePredicate` values.
3. **OS-enforced capability manifest plus external-benchmark conformance.** Modules 03 and 07 land these together: manifest-derived sandbox is the physics layer that stops a plausible destructive proposal, and the two external benchmarks (Aider Polyglot subset + SWE-bench Lite) are the eval-first anchor that makes the leaderboard falsifiable.

Everything else in the module map (typed action union in module 04, event trace in module 05, `Rootknot` re-orientation and Whisperer/Fence/Auction as contracts in module 06, close in module 08) either sits on those three foundations or extends them.

v0.4.0 is the pipeline that answers the substrate critique in kind. It does not add features; it re-seats the ones v0.3 shipped so authority lives in the environment, not the model.

---

## Non-negotiable invariants

The following hold across every module in this pipeline. A module that would break any of them halts and files an ADR before proceeding.

1. **Rootknot is sacred.** The word, the concept, and the signed provenance capability remain the philosophical spine. v0.4 does not rename, demote, or replace it. Module 06 **extends** its schema (`environment_signature`, `acceptance_suite_digest`, `predicate_results`, `manifest_digest`) and lands Invariant RK-3; existing v1 sidecars continue to verify under a compatibility reader path so v0.3 workspaces are not stranded.
2. **Definition of Done is a yes/no test.** Every module's DoD lists conditions that a fresh cold reader can execute and read a boolean out of. Qualitative bullets ("well documented", "sufficiently tested") are forbidden. Where prose is needed, it lands in the module's `Flagged gaps` section, not in the DoD.
3. **No new runtime dependency without a fresh ADR.** v0.3.0 dependencies (`pyyaml`, `httpx`, `zstandard`, `rich`, `cryptography`) are the baseline. Substrate work will need at least `pydantic` (already in dev extras), `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, and optionally `dagger-io`. Each addition to `[project.dependencies]` (as opposed to `[project.optional-dependencies]`) requires an ADR under `docs/ADRs/` with rejected alternatives before the module can commit.
4. **`pytest -q`, `ruff check`, `mypy` green at every commit.** Not "green by end of pipeline" — green at every commit. If a module needs a scaffolding commit that would break the suite, it lands behind a feature flag with the flag defaulting to off.
5. **Cron watchdog + per-sub-task cadence.** The pipeline runs under a scheduled watchdog that fires a resume/alignment pulse. The pulse reads `active_module` from `_BUILD/ract_v0.4.0_substrate/build_state.md` and continues execution. Operator is designer + course-corrector, not per-module green light.
6. **Local commits only.** No `git push` is issued from the pipeline. Tag `v0.4.0` at close is local; publication is a separate operator action.

---

## Module map

- **module_01 — Acceptance predicates + IntentCompiler.** Origin: SUBSTRATE §2 (Substrate Layer 1) and §11 signals 1 and 2. Adds `src/ract/core/predicate.py`, `src/ract/core/compile.py`, `src/ract/core/gates.py`; rewrites T1 to a predicate-based check; downgrades `ProgressOracle` to a scheduling heuristic; every run commits `evals/runs/<run_id>/suite.json`.
- **module_02 — Transactional execution.** Origin: SUBSTRATE §3 (Substrate Layer 2) and §11 signal 3. Adds `src/ract/core/transaction.py`, `src/ract/executor/worktree.py`, `src/ract/executor/runtime.py`; every step opens a `StepTransaction` in a git worktree named `rootact/step/<step_id>` on a step branch, optionally inside a container; `HandshakeRegistry` rewritten so unresolved handshakes block dependent commits at the git layer. New CLI: `ract session ls`, `ract session diff <step_id>`.
- **module_03 — Capability manifest + OS-enforced sandbox.** Origin: SUBSTRATE §4 (Substrate Layer 3) and §11 signals 4, 5, 6. Adds `src/ract/security/manifest.py` (schema + validator), `src/ract/security/sandbox_linux.py` (bwrap + Landlock + seccomp), `src/ract/security/sandbox_macos.py` (Seatbelt). Changes `--yolo` from "disable prompts" to "auto-widen manifest within pre-declared bounds." Adversarial `tests/security/` corpus covers path traversal, `/proc/self/root/*` synonym, network egress, syscall bypass.
- **module_04 — Typed action union + conformance corpus.** Origin: SUBSTRATE §5 (Substrate Layer 4) and §11 signals 7 and 8. Adds `src/ract/core/actions.py` (closed Pydantic union), `src/ract/providers/schema.py` (adapters for OpenAI Structured Outputs, Anthropic tool use, JSON Schema fallback), `src/ract/providers/validator.py`. Ships `evals/conformance/` with three categories (schema compliance, tool discipline, refusal fidelity). Adds `ract conformance run --provider <name>`; gates router registration on a passing recent report.
- **module_05 — Event trace as the product.** Origin: SUBSTRATE §6 (Substrate Layer 5) and §11 signals 9, 10, 11. Adds `src/ract/trace/events.py` (closed event kinds, hash-chained JSONL to `evals/runs/<run_id>/events.jsonl`), `src/ract/trace/writer.py`, `src/ract/trace/otel.py` (OTLP export). Adds CLI verbs `ract trace replay|fork|diff|to-test`. Reduces `RunReporter` to a projection over the event log. Publishes `docs/EVENTS.md` versioned semver.
- **module_06 — Rootknot re-orientation + Whisperer/Fence/Auction as contracts.** Origin: SUBSTRATE §7 and §8 and §11 signals 12, 13, 15. Extends `Rootknot` with `environment_signature`, `acceptance_suite_digest`, `predicate_results`, `manifest_digest`. Lands Invariant RK-3 (Environmental Attestation). Whisperer becomes a pre-plan contract (auto-injects `DialectBrief` into planner prompts); Fence intercepts every deletion at the executor before it enters a transaction; Auction runs as a scheduled between-iteration environment sweep. `__root_author__` moves to display-only under `ract --about`.
- **module_07 — Evals: Aider Polyglot subset + SWE-bench Lite + LEADERBOARD.** Origin: SUBSTRATE §9 and §11 signal 16. Lands 10 Aider Polyglot problems and 5 SWE-bench Lite instances under `evals/`, each with container-per-task execution and git-patch output where applicable. Adds `evals/LEADERBOARD.md` per provider. CI runs a reduced size (1 problem per corpus) on every PR; nightly full run on main.
- **module_08 — v0.4.0 close.** CHANGELOG `[0.4.0]` entry per module; README Verify section refreshed to name every new invariant, CLI verb, and eval; VERSION + pyproject + `__init__` set to `0.4.0`; `test_version.py` sweep; `docs/ROADMAP.md` refreshed with the honest distance-to-excellent list carried from every module's Flagged gaps; tag `v0.4.0`.

---

## Bar policy

Same shape as v0.3 and v0.3.1, one turn tighter.

- **DoD is the floor.** Each module's Definition of Done is a boolean checklist. When it passes, the module commits.
- **Log Flagged gaps at close.** After the DoD-met commit, the module author fills in the `Flagged gaps (to log at close)` section with what "excellent" would have demanded past the DoD. That log is the input to the v0.5 hardening pipeline; it is never silently dropped.
- **v0.4 already raises the bar past v0.3.** The DoDs in this pipeline embed the SUBSTRATE §11 signals as boolean tests. There is no module whose DoD would have passed in v0.3.1; the bar has moved.
- **DoDs are pre-signed by the pipeline, not renegotiated in-module.** A module that finds its DoD infeasible halts, surfaces the reason to the operator, and does not lower the DoD to what the module happens to have produced. The failure mode this policy exists to prevent is silent DoD softening between modules.

---

## Cadence and watchdog

- **Cadence:** per-sub-task. Each step within a module externalizes state to `build_state.md` before advancing. No multi-step in-flight state that only exists in the model turn.
- **Watchdog:** cron. A scheduled resume/alignment pulse fires at a cadence recorded in `build_state.md` under `watchdog`. The pulse reads `active_module` from the ledger and continues execution from that module's first not-yet-DONE step. The main session registers the cron id; that id is logged in the ledger's Status log at kickoff.
- **Advance rule:** the resume pulse never invents a new module. If `active_module` is `module_04.md` and step 3 is not yet DONE, the pulse resumes at step 3 of module_04. Module transitions happen only when the current module's DoD is boolean-passing and its Flagged gaps are logged.
- **Halt-and-file rule:** any module that cannot meet its DoD halts, files a note to the ledger's Status log, and yields. The pipeline does not skip a module to reach the tag.

---

## Signals checklist (final gate before `v0.4.0` tag)

module_08 does not commit the tag until every one of the following is `true`. Each item is the corresponding SUBSTRATE §11 signal, restated verbatim as a pipeline exit criterion.

- [ ] `AcceptanceSuite` compiled and committed per run, discoverable in `evals/runs/<run_id>/suite.json`.
- [ ] Loop termination T1 reads: all required predicates evaluate true against the final snapshot.
- [ ] Every step runs in a git worktree named `rootact/step/<step_id>` on a step-specific branch.
- [ ] Every step runs inside a sandbox derived from a capability manifest.
- [ ] The manifest is published for every run.
- [ ] Bubblewrap plus Landlock plus seccomp on Linux; Seatbelt on macOS. Enforcement at the OS layer, not the harness.
- [ ] Every model action is a member of a closed Pydantic union, validated at the provider boundary.
- [ ] A per-provider conformance report card lives in `evals/conformance/` and gates router registration.
- [ ] Every run produces a hash-chained event log at `evals/runs/<run_id>/events.jsonl`.
- [ ] OpenTelemetry spans exportable to any OTLP backend.
- [ ] `ract trace replay|fork|diff|to-test` work end-to-end.
- [ ] `Rootknot` carries both a `generator_signature` and an `environment_signature`.
- [ ] Invariant RK-3 (Environmental Attestation) implemented and tested.
- [ ] `__root_author__` is display-only, no role in any invariant.
- [ ] Whisperer runs as a pre-plan contract; Fence intercepts every deletion; Auction runs as a scheduled environment sweep.
- [ ] `evals/LEADERBOARD.md` shows Aider Polyglot subset, SWE-bench Lite, conformance, and security pass rates per provider.

If any of the sixteen is red, module_08 is not done and the tag does not land.

---

## Reference set

The closed list of public sources v0.4 design draws from. Any design decision inside a module fragment must cite this set (by section or entry). A design that needs a source outside this list halts and files an ADR before proceeding.

**Substrate spec citations carried forward from `RACT_SUBSTRATE_SPEC.md`:**

- Aider Polyglot benchmark (six-language coding eval with unified-diff output and two-attempt pattern; 225 Exercism-derived exercises). Public repository: `https://github.com/Aider-AI/aider`; leaderboard at `https://aider.chat/docs/leaderboards/`.
- SWE-bench and SWE-bench Lite (repository-scale coding eval with container-per-task, git-patch output, held-out test suite verification). Public site: `https://www.swebench.com/`; repository: `https://github.com/SWE-bench/SWE-bench`.
- OpenHands V1 SDK (multi-LLM routing, native sandboxed execution, built-in security analysis, OpenTelemetry tracing). Public repository: `https://github.com/All-Hands-AI/OpenHands`.
- Temporal durable-execution model (workflow-plus-activities split, event-sourced replay, deterministic workflow code). Public documentation: `https://docs.temporal.io/`.
- Dagger Container Use (per-agent git worktree plus container pair, auto-committed environment changes). Public repository: `https://github.com/dagger/container-use`.
- Git worktrees primitive. Public documentation: `https://git-scm.com/docs/git-worktree`.
- Claude Code subagents with `isolation: worktree` frontmatter. Public documentation on Anthropic's site.
- Bubblewrap (bwrap) unprivileged sandboxing on Linux. Public repository: `https://github.com/containers/bubblewrap`.
- Landlock LSM (unprivileged filesystem access control). Public documentation: `https://landlock.io/` and Linux kernel documentation.
- seccomp-bpf syscall filtering. Public Linux kernel documentation: `https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html`.
- macOS Sandbox (Seatbelt) and `sandbox-exec`. Public Apple documentation.
- Sandlock.mcp per-tool capability sandboxing pattern.
- OpenTelemetry API, SDK, and OTLP exporters for Python. Public repository: `https://github.com/open-telemetry/opentelemetry-python`; specification at `https://opentelemetry.io/`.
- OpenTelemetry GenAI Semantic Conventions Special Interest Group. Public specification work: `https://github.com/open-telemetry/semantic-conventions`.
- OpenAI Structured Outputs. Public documentation at OpenAI's API reference.
- Anthropic tool use API. Public documentation at Anthropic's API reference.
- JSON Schema (Draft 2020-12). Public specification: `https://json-schema.org/`.
- Instructor library (Pydantic-shaped LLM output validation with retry). Public repository: `https://github.com/jxnl/instructor`.

**Standard engineering references:**

- PEP 621 (`pyproject.toml` metadata). Public specification.
- Pydantic v2 documentation. Public site: `https://docs.pydantic.dev/`.
- RFC 8032 (Edwards-curve Digital Signature Algorithm; ed25519). Public IETF RFC.
- `cryptography` Python library. Public documentation: `https://cryptography.io/`.
- `pre-commit` framework. Public site: `https://pre-commit.com/`.
- Keep a Changelog. Public site: `https://keepachangelog.com/`.
- Semantic Versioning 2.0.0. Public site: `https://semver.org/`.

**Prior-art incidents named in the SUBSTRATE spec (used as adversarial test cases in module_03):**

- Claude Code home-directory `rm -rf ~/` trailing-slash incident (SUBSTRATE §4.1).
- Cursor 70-file deletion despite explicit "DO NOT RUN ANYTHING" instruction (SUBSTRATE §4.1).
- Replit agent production-database deletion during code freeze (SUBSTRATE §4.1).
- April 2026 Bubblewrap escape at Ona via `/proc/self/root/usr/bin/npx` denylist-versus-allowlist gap (SUBSTRATE §4.2).

Anything outside this closed list needs an ADR before it enters the design. The pipeline treats the SUBSTRATE spec's own citation numbers (`index 21-1`, `index 29-1`, `index 37-1`, and so on) as the canonical anchor for the primary claims; module fragments cite by SUBSTRATE section number rather than duplicating the numeric index.

---

## Predecessor context

- **v0.3.0** tagged 2026-07-25. REBUILD-spec agenda essentially met. Rootknot signed capability with sidecars + SQLite index + RK-1/RK-2 verifier + T1–T7 loop + tiered threat model + seven ADRs + benchmark harness.
- **v0.3.1 hardening pipeline** initiated 2026-07-26, superseded the same day when the audit against the SUBSTRATE spec surfaced the 14/16 gap. Its items (config schema-version enforcement, self-contained sidecars, offline verify, benchmark honesty, pre-commit lockdown, executor concurrency proof) remain valid work but are smaller-scoped than the substrate rebuild and are deferred to post-v0.4.

The v0.4 pipeline treats the v0.3.1 flagged-gaps log as a **companion backlog**, not as competing priorities. Where a v0.3.1 gap and a v0.4 module fragment intersect (e.g., self-contained sidecars in v0.3.1 module_02 and Rootknot re-orientation in v0.4 module_06), v0.4 subsumes the earlier gap and the v0.3.1 module is marked resolved when v0.4 lands.

---

## Closing

The reviewer's substrate critique and the v0.3.1 audit are the same sentence expressed at two depths. Answering them means shipping a substrate that a senior architect recognizes as her own species: acceptance predicates the environment evaluates, transactional worktrees the model cannot bypass, capability manifests the OS enforces, typed action unions the validator refuses to widen, and an event trace the run report projects from rather than summarizes over. The rootknot survives sacred through all of it, because the concept — a small verifiable anchor that ties every artifact to its origin — is exactly right; only the origin needed to change. v0.4 is the pipeline where the origin becomes the environment that verified the artifact.

That is the version there is nothing left to comment on.
