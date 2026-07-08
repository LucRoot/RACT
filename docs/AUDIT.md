# Rooted by Dr. Lucas Root, Ph.D.

# RootAct Codebase Audit

**Date:** 2026-07-08 (post-competitive-feature wave)  
**Scope:** `C:/RootClaw/rootact/` source, tests, docs, and build artifacts intended for public release.  
**Auditor:** Kimi Code CLI  
**Methodology:** `ruff check`, `ruff format --check`, `pytest -q --cov=rootact`, `mypy src tests`, manual boundary review.

---

## Executive Summary

RootAct (public name: **RACT**) is a standalone, model-agnostic Agentic Coding Tool built around the `Rooted[T]` assumption-driven programming quirk. The codebase is lint-clean, fully formatted, type-clean, and the test suite is green. It is **not** the same system as Internal: RootAct contains no Internal/Internal code, training artifacts, or proprietary management-layer concepts. This audit reflects the current public-release candidate after the competitive-feature build wave.

**Current test status:** 1155 passed, 0 failed, 1 skipped (Windows-specific).  
**Overall coverage:** 94% (575 uncovered statements out of 9120).  
**Overall risk:** Low. Core loops, provider routing, harness integration, provider resilience (capability-based fallback chains + health checks), run modes, session/rollback, project documents, CLI toggles, self-test, code-review diff, memory arena, quality scorecard, artifact provenance, built-in skills, provider presets, operator handshakes, run reports (with JSON export), MCP integration (including `rootact mcp list`), DiffApplier (including `rootact diff apply`), retrieval adapter (including `rootact retrieval search`), error-mask detection, symbol graph, codebase historian, duplication guard, historian-aware milestone planning, lint/format repair loop, branded terminal UI (`rootact --welcome`, colorized input/output, rich tables for listing commands), and the Root-Knot-anchored self-recursing build loop are wired and exercised. The loop itself is hardened with per-iteration timeouts, configurable test commands, intent-oscillation detection, and richer failure feedback; the `--loop` CLI path is covered by integration tests. Public docs (README, QUICKSTART, PROVIDER_SETUP, SKILL_AUTHORING, PHILOSOPHY) cover installation, first run, loop mode, all 10 built-in skills, provider presets (including Z.ai, Moonshot, OpenRouter, Ollama, and local Internal proxy), reports, handshakes, MCP tools, retrieval, diff application, novelty scan, whisper, auction, fence, load-bearing, refactor, openapi, plan replay, doctor, the welcome screen, and a subtle author bridge to the AI Agent Playbook mailing list. README and docs/index.md include low-pressure CTAs linking to `https://lucasroot.pro/ai-agent-playbook-thanks`; the HF Space landing page mirrors the link. Fresh projects created via `--init-provider` now receive a default `prompts/manager.txt`, and the harness falls back to a bundled prompt if the project prompt is missing.

**Latest burn-in driven fixes:** The Executor now strips markdown code fences (e.g. ` ```python ... ``` `), extracts JSON artifact wrappers (e.g. `{"artifact": "src/foo.py", "content": "..."}`), and strips leading artifact-path lines (e.g. `tests/test_greeter.py\r\n```python`) from generated artifacts before writing them. The artifact-path strip is separator-agnostic so Windows backslash expectations match forward-slash model output. `DuplicationGuard` now allows rewrites of symbols within their own module/file and only flags cross-module duplication, preventing false-positive blocks when a model edits an existing file in place. End-to-end loop burn-in against a fast mock local LLM completed successfully: the greeter-refactor intent produced `_fmt` → `format_message` rename, removed duplicated capitalization in `surprise`, preserved the Root Knot, and passed tests across three loop iterations; stagnation was correctly detected when the deterministic mock returned identical content. The Manager rejects `tool_call` plan steps when no MCP servers are configured, and the Executor treats an empty MCP registry as if no registry were provided, eliminating silent stub failures in no-MCP projects. Local HTTP streaming no longer sends an `Authorization` header, and OpenAI-compatible streaming errors are surfaced as Rooted failures rather than uncaught exceptions. `TestFailureDiagnoser._infer_source_from_test()` now catches `UnicodeDecodeError` when reading malformed test files. `SymbolGraph._link_file()` was rewritten to use recursive traversal with proper scope tracking; the previous `ast.walk`-based implementation assigned edges to the wrong scope because `ast.walk` yields nodes in breadth-first order. `LoopController._check_root_knot()` now only inspects `.py` artifacts and deduplicates checked paths, so runtime reports such as `test_results.txt` no longer trigger false "regression" decisions. `LoopController` also detects intent oscillation (A->B->A state regressions) and treats them as continuity failures. `RactDoctor._check_provider_reachability()` now filters out non-dict provider configs before instantiating `ProviderRouter`, avoiding an `AttributeError` when a provider entry is malformed. `RunModeOrchestrator._resume_session()` now catches `KeyError` raised by `SessionStore.load()` in addition to `FileNotFoundError`, surfacing a clear `FileNotFoundError` when no prior session exists.

---

## 1. Static Analysis

| Tool | Result |
|------|--------|
| `ruff check src tests scripts` | All checks passed |
| `ruff format --check src tests scripts` | 228 files already formatted |
| `mypy src tests` | All checks passed |
| `bandit -r src tests` | No security hits |

**Notes:**
- `__root_author__ = "Dr. Lucas Root, Ph.D."` is present in every `.py` file.
- `__ract_name__ = "RACT"` is present in every non-`__init__.py` source and test file.
- `_ROOT_KNOT = object()` is present in every non-`__init__.py` source and test file.
- `E402` is intentionally disabled project-wide so authorship/sentinel markers can sit before imports.

---

## 2. Test Quality

- **Collected tests:** 1156
- **Passing:** 1155
- **Failing:** 0
- **Skipped:** 1 (Windows-specific)
- **Coverage:** 94% (575 uncovered statements)
- **Uncovered modules:** none at 0%; all core modules are exercised.
- **Notable coverage milestone:** `loop_controller.py` is at 99% (1 uncovered line: the quality-floor regression branch in `_decide`).

The test suite exercises the harness, provider router, manager/planner/executor, CLI toggles, session store/rollback, project document, approval callback, edge-case builders, self-test benchmark, code-review mode, Root signature utilities, loop controller, milestone oracle, progress oracle, provider presets, built-in skill library, run reporter, handshake registry, MCP adapter, DiffApplier, retrieval adapter, test-failure diagnoser, symbol graph, codebase historian, duplication guard, historian-aware loop planning, lint/format repair, run-mode orchestration, version utilities, and the multi-file symbol renamer.

---

## 3. Boundary Statement: RootAct ≠ Internal

RootAct is intentionally separate from Internal and the `frontline-poc` Internal work:

- No Internal proxy, reasoner, decisioner, or reflector code is imported or referenced.
- No Internal model training artifacts or dual-head orchestration logic is present.
- The `Rooted[T]` quirk is a public-facing design choice, not Internal-specific IP.
- Any learnings from RootAct may flow **one way** into Internal upgrades, but Internal concepts never flow into RootAct.

The separation is enforced by `scripts/verify_internal_rootact_separation.py` (scans `src/rootact` for Internal/Internal imports and references) and documented in `docs/SEPARATION.md`.

---

## 4. Competitive Feature Wave

The following seven capabilities were implemented to close gaps versus Cursor, Claude Code, Lovable, and other frontier agentic tools. Each is signed with the Root Knot and covered by tests.

| Capability | Module(s) | Status | Notes |
|------------|-----------|--------|-------|
| **1. Progress Oracle / Milestone-Driven Loop** | `loop_planner.py`, `milestone_oracle.py`, `progress_oracle.py`, `loop_controller.py` | ✅ | The loop plans milestones, verifies them, and detects stagnation/regression rather than running on time alone. |
| **2. Signature Survival Layer** | `signature_guardian.py`, `cli.py`, `executor.py` | ✅ | Golden hash guards the signature markers; the Executor re-injects the Root Knot if a generated file loses it. `rootact --about` surfaces the public name. |
| **3. Provider Presets** | `provider_presets.py`, `cli.py` | ✅ | One-command setup for `local`, `openai`, `anthropic`, `zai`, `moonshot`, and `openrouter` via `--init-provider`. |
| **4. Built-in Skill Library** | `builtin_skill_library.py`, `builtin_skills/*.json`, `cli.py` | ✅ | `rootact skills list/install/install-all` with 10 signed templates: python-package, fastapi-app, react-component, test-generation, documentation-update, cli-tool, library-refactor, api-client, data-pipeline, config-driven-service. Templates are written in the RACT voice (Root Knot markers, Rooted results, LR:: notes, anti-rot constraints). |
| **5. Run Report** | `run_reporter.py`, `cli.py` | ✅ | `rootact report --last` and `--session` summarize the last loop/session. `--format json` and `--output <path>` export structured reports for scripts and CI. |
| **6. Operator Handshake Registry** | `handshake_registry.py`, `cli.py` | ✅ | High-risk milestones return a `handshake` verdict; the loop continues and the operator reviews later with `rootact handshakes list/approve/reject/defer`. |
| **7a. MCP Adapter** | `mcp_adapter.py`, `executor.py`, `harness.py`, `manager.py`, `cli.py` | ✅ Integrated | `McpToolRegistry` loads from `mcp_servers` config, lists tools, and routes `tool_call` plan steps through `Executor`. `rootact mcp list` exposes configured tools to users. |
| **7b. DiffApplier** | `diff_applier.py`, `executor.py`, `harness.py`, `cli.py` | ✅ Integrated | `Executor` detects unified-diff content and applies it surgically to existing files. `rootact diff apply --patch <path> [--dry-run]` exposes this directly to users. |
| **7c. Retrieval Adapter** | `retrieval_adapter.py`, `harness.py`, `cli.py`, `prompts/manager.txt` | ✅ Integrated | `Harness` loads a `retrieval` adapter (keyword or web) and appends top-k snippets to the Manager prompt before planning. `WebSearchAdapter` supports Serper, Brave, Bing, and generic search APIs. `rootact retrieval search` lets operators preview retrieved context. |
| **8. Loop Hardening** | `loop_controller.py`, `tests/test_loop_controller.py` | ✅ | Per-iteration `ThreadPoolExecutor` timeout prevents hung providers from stalling the loop; `test_command` is configurable; failed milestone backlogs fall back to no-milestone mode; iteration errors, test summaries, and missing Root Knot files are fed back into the next prompt. |
| **9. Test Failure Diagnosis and Repair** | `test_failure_diagnoser.py`, `loop_controller.py` | ✅ | Parses pytest output, extracts failing tests, infers relevant source files from tracebacks and test imports, and feeds a focused repair prompt back into the loop. Configurable `repair_attempts` lets the loop recover from regressions instead of stopping. |
| **9a. Generated Test Preflight Validation** | `preflight_test_validator.py`, `loop_controller.py` | ✅ | Catches syntax errors and obvious missing imports (e.g., `re`, `json`, `pytest`) in generated test artifacts before invoking pytest. Failed preflights consume a repair attempt and skip the expensive test run. |
| **9b. Module-Family Tunneling Guard** | `module_family_tracker.py`, `loop_controller.py` | ✅ | Classifies each completed milestone into a semantic family and injects a `[DIVERSITY PROMPT]` after N=3 consecutive same-family completions, seeded with alternative use cases from `rootact_use_cases.jsonl`. |
| **9c. Error-Memory / Failure-Pattern Summarization** | `error_memory.py`, `loop_controller.py` | ✅ | Distills raw pytest output and iteration errors into compact, ranked failure patterns (missing imports, Root Knot omissions, timeouts, refactor-tax breaches, test failures) and replays them as loop memory so the model avoids repeated traps. |
| **9d. Strategic Context Clear After Stagnation Streak** | `loop_controller.py` | ✅ | Tracks consecutive `stagnant` decisions; after `strategic_clear_threshold` stagnant iterations it clears `ErrorMemory`, resets the stagnation counter, and injects a `[STRATEGIC CONTEXT CLEAR]` intent that restates the original goal and demands a materially different approach. |
| **9e. Task-Aware Temperature Routing** | `temperature_router.py`, `manager.py`, `executor.py`, `harness.py` | ✅ | `TemperatureRouter` maps step actions and planning intents to temperatures: low (`code_temp=0.15`) for code generation, moderate (`plan_temp=0.4`) for planning, higher (`brainstorm_temp=0.55`) for brainstorming. Defaults are overridable via `rootact.yaml` `temperature` config. |
| **10. Anti-Rot Phase A: Provider Fallback Chain** | `providers/router.py`, `providers/base.py`, `capability_registry.py`, `executor.py` | ✅ | `ProviderRouter` scores adapters by capability hint, exposes ordered `fallback_chain()`, and `Executor` tries the chain on provider failure. Per-slot `health_check()` probes `{url}/models` (with auth for OpenAI-compatible, without for local). |
| **11. Anti-Rot Phase A: Error-Mask Detector** | `error_mask_detector.py`, `safety_guardrails.py` | ✅ | AST-based detector hunts `except Exception: pass`, bare `except:`, silent `return None`, logging-only handlers, and `contextlib.suppress(Exception)`. Permitted only with `# error-mask-permitted: cause=<reason> recovery=<strategy>`. Integrated into `SafetyGuardrail` so generated artifacts are blocked. |
| **12. Anti-Rot Phase B: Verifier Rubric v0.3** | `quality_scorecard.py` | ✅ | Ten-signal verifier rubric with deletion bonus, error-mask penalty, duplication penalty, and gravity adherence. `Verdict` dataclass + `score_verdict()` API; backward-compatible `compute_score(plan)` preserved. |
| **13. Anti-Rot Phase B: Refactor Tax Ledger** | `refactor_ledger.py`, `loop_controller.py`, `cli.py` | ✅ | Tracks new vs. maintained lines per session. Default 3:1 threshold blocks loop `done` unless `--allow-debt` is passed. Persists to `.rootact/refactor_ledger.json`. |
| **14. Anti-Rot Phase B: Codebase Gravity Scorer** | `gravity_scorer.py` | ✅ | AST-based symbol index with reference counting and PageRank-like module centrality. `top_k(intent)` exposes load-bearing symbols for planner context. Mtime-aware cache. |
| **15. Anti-Rot Phase C: Symbol Graph + Codebase Historian + Duplication Guard** | `symbol_graph.py`, `codebase_historian.py`, `duplication_guard.py`, `executor.py`, `harness.py`, `loop_planner.py` | ✅ | Pure-Python symbol graph indexes functions/classes/modules and call references. Historian layers git blame context on top and answers "what already exists like this?". Duplication guard blocks Executor writes that reproduce existing symbols above the 0.85 similarity threshold. `LoopPlanner` queries the Historian during milestone planning and instructs the management LM to avoid silent duplication. |
| **16. Use Case: Lint and Format Fix Loop** | `lint_format_repair.py`, `loop_controller.py` | ✅ | Runs `ruff check`, `ruff format --check`, and `mypy` after tests pass. Parses output into `LintIssue` objects and queues a repair iteration when static analysis fails. Skips checks when no Python files are present. |
| **17. Use Case: Multi-File Refactor with Symbol Rename** | `symbol_renamer.py`, `symbol_graph.py`, `cli.py` | ✅ | `rootact refactor --old <name> --new <name> [--module <module>] [--dry-run]` performs AST-guided rename of module-level functions/classes. Renames definitions, same-module bare references, and `from module import name` imports in other modules. Intentionally conservative: no attribute access or local-variable renames. |
| **18. Use Case: Documentation Generation from Code** | `doc_generator.py`, `cli.py`, `documentation_mode.py` | ✅ | `rootact docs generate [--output-dir <dir>]` scans the project, extracts module/class/function docstrings and signatures, and writes Markdown API docs to `docs/api`. Provides the concrete engine behind Documentation Mode. |
| **19. Use Case: Configuration-Driven Project Templates** | `project_initializer.py`, `project_templates/*.json`, `cli.py`, `provider_presets.py` | ✅ | `rootact init --template <name> --provider <name>` scaffolds a new project with `rootact.yaml`, default prompt, starter source/tests/README, and a built-in skill. Refuses to overwrite existing projects. |
| **20. Use Case: OpenAPI Client/Server Generation** | `openapi_client_generator.py`, `openapi_server_generator.py`, `openapi_spec_parser.py`, `cli.py` | ✅ | `rootact openapi generate-client` emits an `httpx`-based Python client; `rootact openapi generate-server` emits a FastAPI server module. Both read OpenAPI 3 JSON/YAML specs and support query/path/body parameters. |
| **21. Use Case: Plan Replay and Deterministic Re-execution** | `plan_replay.py`, `plan_serializers.py`, `session_store.py`, `cli.py` | ✅ | `rootact plan export --session <id> --output <path>` saves a session plan to JSON; `rootact plan replay --plan <path> --dry-run` replays the plan and reports per-step success. |
| **22. Use Case: Project Health Diagnostics** | `doctor.py`, `cli.py` | ✅ | `rootact doctor --config <path>` inspects `rootact.yaml`, provider configuration, prompt files, and skill references, reporting pass/fail diagnostics before invoking a model. |
| **23. Provider Cost/Latency Tracking** | `providers/base.py`, `providers/openai_provider.py`, `executor.py`, `loop_controller.py`, `run_reporter.py` | ✅ | Per-step latency, token usage, and cost are extracted from provider responses, aggregated per execution, rolled up per loop, and rendered in `rootact report --last`. Local/HTTP providers expose optional cost configuration; metrics survive into JSON exports. |
| **24. Load-Bearing Weirdness Annotation Guard** | `load_bearing_guard.py`, `executor.py`, `harness.py`, `loop_controller.py`, `cli.py` | ✅ | `# load-bearing: <reason>` comments protect the following function/class/block. `Executor` refuses writes that modify a protected region unless `allow_load_bearing_override` is set via `--allow-load-bearing` or `rootact.yaml`. `rootact load-bearing list` surfaces all annotated regions. |
| **25. Novelty Budget Anti-Rot Guard** | `novelty_budget.py`, `executor.py`, `harness.py`, `loop_controller.py`, `cli.py` | ✅ | Each session has a novelty budget (default 15 points). New files (3), new public symbols (6), dependency-file changes (8), and gravity deviations (2) consume points. `Executor` blocks writes that would exceed the budget unless `--allow-novelty-overrun` or `allow_novelty_overrun: true` is set. Budget state persists per session in `.rootact/novelty_budget.json`. |
| **26. Compression-Based Novelty Detector** | `compression_novelty_detector.py`, `executor.py`, `harness.py`, `cli.py` | ✅ | Trains a zstd dictionary on the existing codebase and scores each artifact by comparing compression with/without that dictionary. Low novelty flags possible duplication; high novelty flags genuine outliers. `Executor` records scores in `ExecutionReport.artifacts["novelty_scores"]`, and `rootact novelty scan [--json]` lets operators preview the signal directly. Skips dependency/build/cache directories (`.venv`, `.git`, `node_modules`, etc.). |
| **27. Legacy Whisperer Subagent** | `legacy_whisperer.py`, `harness.py`, `cli.py` | ✅ | Pre-planning subagent that reads the symbol graph, recent git history, and style fingerprint of the most-referenced files, then produces a dialect/history brief for the management model. Integrated into `Harness.run` when `legacy_whisperer.enabled: true`. Exposed as `rootact whisper --intent "..." [--paths ...]`. |
| **28. Dead Code Auction** | `dead_code_auction.py`, `cli.py` | ✅ | Identifies Python modules that are older than a configurable threshold (default 180 days) and have no inbound references from other project modules. Lists candidates for operator review; nothing is deleted automatically. Exposed as `rootact auction list [--min-age-days N] [--json]`. Skips dependency/build/cache directories and test files by default. |
| **29. Chesterton's Fence Subagent** | `chestertons_fence.py`, `cli.py` | ✅ | Before removing or bypassing legacy code, reads the file, recent commits, and blame for the target lines, then asks the management provider for a plausible reason the code exists. Low-confidence responses ("no plausible reason found") flag the change for review. Exposed as `rootact fence inspect --file <path> [--lines N-M]`. |
| **30. Branded Terminal UI** | `tui.py`, `cli.py` | ✅ (tui.py 100%) | `rich`-based branded console with gold/blue/red/green/amber palette, distinct cyan for user-input text and orchid for direct system-to-user text, ASCII Root-Knot logo, `rootact --welcome`, and rich tables for `auction`, `novelty`, `report`, `handshakes`, `skills`, `mcp`, `retrieval`, `load-bearing`, and `doctor` listing commands. UTF-8 reconfiguration prevents Windows legacy-console crashes. |

---

## 5. Harness Integration Status

All previously unwired modules are now integrated or removed. The harness path uses `PreflightValidator`, `Harness`, `PlanValidator`, `DependencyGraph`, `Executor` (with `SafetyGuardrail`, `SignatureRegistry`, `HookManager`, `ArtifactStore`/`ArtifactTracker`, `ProvenanceTracker`), and `HarnessReportEnricher`.

| Module | Coverage | Classification | Use-Case Link | Priority |
|--------|----------|----------------|---------------|----------|
| `rootact_runner.py` | 92% | high-level run entry point | All CLI and programmatic use cases | High |
| `loop_controller.py` | 98% | Root-Knot-anchored recursion engine with timeout, configurable test command, failure feedback, intent-oscillation detection, and strategic context clear | Self-recursing build loop | High |
| `milestone_oracle.py` | 92% | milestone verification | Progress Oracle | High |
| `progress_oracle.py` | high | stagnation/regression detection | Progress Oracle | High |
| `loop_planner.py` | 89% | milestone planning | Progress Oracle | High |
| `provider_presets.py` | high | one-command provider setup | Provider Presets | High |
| `builtin_skill_library.py` | high | skill template library | Built-in Skill Library | High |
| `run_reporter.py` | 94% | structured run summaries | Run Report | Medium |
| `handshake_registry.py` | high | operator handshake persistence | Operator Handshake | Medium |
| `signature_guardian.py` | 93% | signature hash verification | Signature Survival | Medium |
| `mcp_adapter.py` | high | MCP client interface + `McpToolRegistry` | MCP Ecosystem | High |
| `diff_applier.py` | high | unified-diff hunk applier invoked by `Executor` | Surgical Editing | High |
| `retrieval_adapter.py` | 95% | keyword retrieval backend invoked by `Harness` before planning | Web/Local Retrieval | High |
| `artifact_store.py` | 66% | wired into `Executor` artifact recording | Artifact Diff Viewer / Intent History Log | Medium |
| `artifact_tracker.py` | 100% | wired into `Executor` artifact tracking | Artifact Diff Viewer | Low |
| `dependency_graph.py` | 96% | wired into `Harness.run` cycle detection | Dependency-Aware Plan Execution | Medium |
| `artifact_diff_wiring.py` | 100% | connects `DiffViewer`/`ChangeSummary` to `ExecutionReport` | Artifact Diff Viewer and Change Summary | Medium |
| `execution_report_diff_extension.py` | 100% | enriches `report.artifacts` with diff/summary | Artifact Diff Viewer and Change Summary | Medium |
| `harness_report_enricher.py` | 100% | wraps `Harness.run` and enriches reports | Artifact Diff Viewer and Change Summary | Medium |
| `hook_system.py` | 91% | pre/post-step hooks wired into `Executor` | User Customization / CI Hooks | Medium |
| `skills_registry.py` | 98% | skill template rendering wired into `Harness` | User Customization / Skills | Medium |
| `user_signature_registry.py` | 98% | signature profile injection wired into `Executor` | User Customization / Signature | Medium |
| `error_classifier.py` | 100% | wired into `Executor` failure path | Safety Guardrails | Medium |
| `executor.py` | 97% | executes plan steps through provider router; writes artifacts to project directory; safety guardrails, hooks, signature injection, provenance/artifact tracking; strips markdown fences and extracts JSON artifact wrappers from generated artifacts | Plan Execution | High |
| `plan_validator.py` | 100% | wired into `Harness.run` | Configuration Validation and Pre-Flight Check | High |
| `safety_guardrails.py` | 100% | wired into `Executor` content check | Safety Guardrails and Forbidden-Pattern Filter | Medium |
| `provenance_tracker.py` | 92% | wired into `Executor` step recording | Intent History Log and Observability Sink | Medium |
| `token_budget.py` | 98% | wired into `Harness.run` context curation | Prompt Compression and Context Curation | High |
| `compression_novelty_detector.py` | high | zstd-dictionary novelty scoring invoked by `Executor` after writes; exposed as `rootact novelty scan` | Anti-Rot / Duplication Detection | High |
| `legacy_whisperer.py` | 90% | pre-planning subagent producing a codebase dialect/history brief; exposed as `rootact whisper` | Anti-Rot / Codebase Dialect | High |
| `dead_code_auction.py` | high | symbol-graph-based dead-code candidate scanner; exposed as `rootact auction list` | Anti-Rot / Deletion Incentive | High |
| `chestertons_fence.py` | high | legacy-code reason subagent using git blame/history; exposed as `rootact fence inspect` | Anti-Rot / Load-Bearing Guard | High |
| `retry_policy.py` | 91% | used by provider adapters for exponential-backoff retries | Provider Resilience | High |
| `documentation_mode.py` | 100% | intent rewriting wired into runner | Documentation Mode | Medium |
| `git_mode.py` | 93% | artifact staging/commit wired into harness | Git Mode | Medium |
| `session_store.py` | 98% | session persistence wired into runner | Session Store and Reload | High |
| `session_rollback.py` | 98% | pre-execution snapshots and rollback wired into runner | Rollback and Checkpoint Engine | High |
| `project_document.py` | 95% | goal/notes prepended to intent; plan updated after run | Project Document Configuration | Medium |
| `approval_callback.py` | 100% | per-step approval callback wired into executor/runner | Approval Queue CLI / CLI Toggles | Medium |
| `self_test_benchmark_mode.py` | 87% | internal pytest suite invoked by `--self-test` | Self-Test Benchmark Mode | Medium |
| `code_review_mode.py` | 97% | diff review invoked by `--review-diff` | Code Review Mode | Medium |
| `quality_scorecard.py` | 100% | deterministic plan quality scoring with CLI surfacing for dry-run and full-run outputs | Quality Scorecard | Low |
| `memory_arena.py` | 99% | integrated into `Harness.run` and `run_rootact` for session-scoped replay and persistence | Memory Arena for Long-Horizon Context | Medium |
| `symbol_graph.py` | 80% | pure-Python symbol graph; foundation for Historian and duplication guard | Anti-Rot Phase C | High |
| `symbol_renamer.py` | 100% | AST-guided multi-file symbol rename; invoked by `rootact refactor` | Multi-File Refactor | High |
| `run_mode.py` | 98% | run-mode orchestrator (yolo/auto/dry-run/resume) with default approval queue | Run Modes | High |
| `version_utils.py` | 100% | dotted-version comparison helpers | Version Handling | Low |
| `doc_generator.py` | high | AST-driven Markdown API doc generator; invoked by `rootact docs generate` | Documentation Generation from Code | High |
| `project_initializer.py` | high | scaffolds new projects from templates + provider presets | Configuration-Driven Project Templates | High |
| `openapi_client_generator.py` | high | generates httpx Python clients from OpenAPI 3 specs | OpenAPI Client/Server Generation | High |
| `openapi_server_generator.py` | high | generates FastAPI server modules from OpenAPI 3 specs | OpenAPI Client/Server Generation | High |
| `openapi_spec_parser.py` | 95% | shared OpenAPI 3 parsing utilities for generators | OpenAPI Client/Server Generation | High |
| `plan_replay.py` | high | save/load/replay plans for reproducibility and regression testing | Plan Replay and Deterministic Re-execution | Medium |
| `doctor.py` | 93% | configuration and project-structure diagnostics; provider reachability skips malformed provider entries | Project Health Diagnostics | Medium |
| `codebase_historian.py` | 65% | symbol graph + git blame context; answers intent similarity queries | Anti-Rot Phase C | High |
| `duplication_guard.py` | 93% | blocks Executor writes above duplication threshold; scope-aware so self-module rewrites are allowed | Anti-Rot Phase C | High |
| `loop_planner.py` | 89% | milestone backlog generator; now queries CodebaseHistorian before planning | Progress Oracle / Loop Planning | High |
| `lint_format_repair.py` | 85% | runs ruff/mypy and builds repair prompts for the loop | Lint/Format Fix Loop | High |
| `utils.py` | 91% | lightweight helpers | Shared helpers | Low |

**Recommendation:** Core MVP wiring is complete. Future work should deepen integration of MCP/DiffApplier/Retrieval into the Executor/Harness planning path and continue expanding the use-case catalog.

---

## 6. What Is MVP-Complete vs. Future Work

### MVP-complete
- Provider adapter layer (`OpenAICompatibleProvider`, `LocalHttpProvider`) with capability-based routing.
- `Manager` wrapper that emits JSON plans.
- `Planner`, `PlanValidator`, `Executor`, `Harness`, and `RootActRunner` wiring.
- CLI with run modes and toggles (`yolo`, `auto`, `reload`, sessions), project document, self-test, and diff review.
- `ProjectDocument` and `SessionStore`.
- Session rollback/checkpoint engine.
- Approval-callback gating in executor/runner.
- Edge-case fixture builders and validators.
- `Rooted[T]` assumption-driven result type and the Root signature quirk.
- Hook system, skill registry, user signature registry, token budget, and report enrichment wired into the default path.
- Documentation mode and git mode wired into CLI/runner/harness.
- Provider retry/backoff implemented.
- Self-test benchmark mode and code-review diff mode wired into CLI.
- Memory Arena integrated into harness/runner for session-scoped replay and persistence.
- Streaming completions implemented across providers, executor, harness, runner, and CLI.
- Quality scorecard surfaced in CLI output for dry-run plans and full execution reports.
- Packaging and CLI smoke test verified.
- Root-Knot-anchored self-recursing build loop (`rootact --loop`) with Progress Oracle milestone tracking.
- Provider presets (`--init-provider`).
- Built-in skill library (`rootact skills list/install/install-all`).
- Run report (`rootact report --last` / `--session`).
- Operator Handshake registry (`rootact handshakes list/approve/reject/defer`).
- Signature survival layer with golden hash and Root Knot re-injection.
- Capability-based provider routing with fallback chains and health checks.
- Error-mask detection in `SafetyGuardrail` with accountability-comment permits.
- Anti-rot verifier rubric v0.3 in `QualityScorecard` with deletion bonus, error-mask penalty, duplication penalty, and gravity adherence.
- Refactor tax ledger blocking loop completion when new-to-maintained ratio breaches threshold; `--allow-debt` override.
- Codebase gravity scorer ranking symbols by reference count and dependency centrality.
- Symbol graph, codebase historian, and duplication guard blocking accidental duplication in the Executor write path.
- Historian-aware milestone planning: `LoopPlanner` queries existing symbols before asking the management LM for a backlog.
- Lint/format repair loop: `LoopController` runs ruff and mypy after tests pass and queues repair iterations for static-analysis failures.
- Compression-based novelty detection: `Executor` records per-artifact novelty scores, and `rootact novelty scan [--json]` surfaces the signal to operators.
- Legacy Whisperer subagent: pre-planning dialect/history brief available via `rootact whisper` and optionally injected into `Harness.run` when enabled.
- Dead Code Auction: lists old, unreferenced modules for operator review via `rootact auction list`; manual removal only.
- Chesterton's Fence: produces a plausible reason legacy code exists before removal; available via `rootact fence inspect`.

### Future work / open gaps
- **Use-case expansion:** continue adding use cases to `rootact_use_cases.jsonl` and building them through the loop.
- **README/Quickstart polish:** keep docs aligned as features land.
- **Real-world loop validation:** run multi-file refactor tasks end-to-end and tune the Progress Oracle thresholds now that the loop has timeout and feedback hardening.

---

## 7. Public-Release Checklist

| Item | Status |
|------|--------|
| All tests passing | ✅ |
| `ruff` lint and format clean | ✅ |
| Signature markers in every `.py` file | ✅ |
| License declared (`PolyForm Noncommercial License 1.0.0`) | ✅ |
| Internal separation verified | ✅ |
| `mypy` clean | ✅ |
| 0% coverage modules resolved | ✅ |
| Use-case catalog expanded (29 accepted, 1 rejected) | ✅ |
| Token budget integrated | ✅ |
| `docs/ARCHITECTURE.md` and `docs/HARNESS.md` aligned with current code | ✅ |
| CI workflow (ruff, pytest, build, CLI smoke test) | ✅ |
| Pre-commit config (ruff, pytest) | ✅ |
| Package builds and CLI installs cleanly | ✅ |
| `rootact_runner` wired into CLI | ✅ |
| Hook, skill, and signature registries wired into harness/executor | ✅ |
| Provider retry/backoff implemented | ✅ |
| Use-case catalog created and validated | ✅ |
| `py.typed` marker included in wheel | ✅ |
| Documentation mode and git mode wired into CLI/runner/harness | ✅ |
| Public quickstart guide | ✅ |
| Provider setup guide | ✅ |
| Skill authoring guide | ✅ |
| GitHub/Hugging Face release design prepared (logo, landing pages, checklist) | ✅ |
| Executor writes generated artifacts to project directory | ✅ |
| Self-recursing build loop (`rootact --loop`) with Progress Oracle | ✅ |
| RACT public-name signature marker (`__ract_name__`) | ✅ |
| Provider presets | ✅ |
| Built-in skill library | ✅ |
| Run report command | ✅ |
| Operator Handshake registry | ✅ |
| Signature survival layer | ✅ |
| Provider cost/latency tracking | ✅ |
| Load-bearing weirdness annotation guard | ✅ |
| Novelty budget anti-rot guard | ✅ |
| Compression novelty scan command (`rootact novelty scan`) | ✅ |
| Legacy Whisperer command and harness integration (`rootact whisper`) | ✅ |
| Dead Code Auction command (`rootact auction list`) | ✅ |
| Chesterton's Fence command (`rootact fence inspect`) | ✅ |
| Branded terminal UI (`rootact --welcome`, colorized I/O, rich tables) | ✅ |
| README install / quickstart / feature polish | ✅ |
| Provider setup guide covers cheap frontier and local options | ✅ |
| Skill authoring guide matches actual JSON/template format | ✅ |

---

## 8. License and Authorship

- **Author:** Dr. Lucas Root, Ph.D.
- **Public project name:** RACT (Root Agentic Coding Tool), reflected by `__ract_name__ = "RACT"` in every non-init Python file.
- **License:** PolyForm Noncommercial License 1.0.0 (free for personal, research, education, and noncommercial use; commercial licensing required).
- **Coder signature:** The `_ROOT_KNOT = object()` sentinel, `__root_author__` marker, and `__ract_name__` marker appear in every non-init Python file as a deliberate, human-coded identity stamp.

---

*This audit supersedes the 2026-07-05 MVP-era audit and the 2026-07-07 pipeline refresh. The previous snapshots are no longer representative of the codebase.*

<!-- RACT 0.1.0 - Initial Public Release -->
