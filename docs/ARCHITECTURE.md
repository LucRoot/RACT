# Rooted by Dr. Lucas Root, Ph.D.

# RootAct Architecture

RootAct is a standalone, model-agnostic Agentic Coding Tool. It turns user intent into structured plans, executes those plans through configurable language-model providers, and writes verified artifacts to disk. The system is built around the `Rooted[T]` assumption-driven result type and the Root Knot coder signature.

## Core Modules

| Module | File | Responsibility |
|--------|------|----------------|
| `Rooted` | `src/rootact/rooted.py` | Assumption-driven result type with confidence and provenance. |
| `Manager` | `src/rootact/manager.py` | Calls the management LM and extracts a structured `Plan`. |
| `Planner` | `src/rootact/planner.py` | Validates plans before execution. |
| `Executor` | `src/rootact/executor.py` | Runs plan steps through the selected provider. |
| `Harness` | `src/rootact/harness.py` | Loads config and wires modules together. |
| `RootActRunner` | `src/rootact/rootact_runner.py` | High-level `run_rootact(config, intent, dry_run)` entry point. Validates config, loads the harness, runs enriched execution, and returns a `Rooted` result. |
| `CLI` | `src/rootact/cli.py` | Thin wrapper over `RootActRunner`; user-facing command-line entry point. |
| `ProjectDocument` | `src/rootact/project_document.py` | Per-project configuration and state. |
| `SessionStore` | `src/rootact/session_store.py` | Persistent session history. |
| `ConfigLoader` | `src/rootact/config_loader.py` | YAML config parsing and validation helpers. |
| `LoopController` | `src/rootact/loop_controller.py` | Root-Knot-anchored self-recursing build loop. Enforces per-iteration timeouts via `ThreadPoolExecutor`, supports configurable `test_command`, surfaces execution errors and missing Root Knot files into subsequent prompts, falls back to no-milestone mode if backlog generation fails, and optionally diagnoses test failures and reruns a repair iteration. |
| `ProgressOracle` | `src/rootact/progress_oracle.py` | Detects stagnation, regression, and completion. |
| `MilestoneOracle` | `src/rootact/milestone_oracle.py` | Verifies milestone deliverables. |
| `LoopPlanner` | `src/rootact/loop_planner.py` | Plans milestones for the recursion loop. |
| `TestFailureDiagnoser` | `src/rootact/test_failure_diagnoser.py` | Parses pytest output, extracts failing tests, infers relevant source files from tracebacks and test imports, and builds a repair prompt for the loop. |

## Provider Layer

| Module | File | Responsibility |
|--------|------|----------------|
| `ProviderAdapter` | `src/rootact/providers/base.py` | Abstract adapter interface. |
| `OpenAICompatibleProvider` | `src/rootact/providers/openai_provider.py` | OpenAI-compatible HTTP endpoints with retry/backoff. |
| `LocalHttpProvider` | `src/rootact/providers/local_http_provider.py` | Local OpenAI-compatible servers (no auth header), inherits retry logic. |
| `Router` | `src/rootact/providers/router.py` | Selects provider by capability hint. |
| `CapabilityRegistry` | `src/rootact/capability_registry.py` | Capability tags and provider scoring. |
| `RetryPolicy` | `src/rootact/retry_policy.py` | Configurable exponential-backoff retry helper. |
| `ProviderPresets` | `src/rootact/provider_presets.py` | One-command setup for common providers. |

## Context, Safety, and Observability

| Module | File | Responsibility |
|--------|------|----------------|
| `TokenBudget` | `src/rootact/token_budget.py` | Ranks context files by relevance and enforces a token budget. |
| `SafetyGuardrail` | `src/rootact/safety_guardrails.py` | Checks generated code against forbidden regex patterns. |
| `PreflightValidator` | `src/rootact/preflight_validator.py` | Validates `rootact.yaml` before work starts. |
| `ArtifactDiffViewer` | `src/rootact/artifact_diff_viewer.py` | Renders human-readable file diffs. |
| `ChangeSummary` | `src/rootact/change_summary_generator.py` | Summarizes added/removed/modified file counts. |
| `ArtifactDiffWiring` | `src/rootact/artifact_diff_wiring.py` | Connects diff/summary rendering to `ExecutionReport`. |
| `DiffExtension` | `src/rootact/execution_report_diff_extension.py` | Attaches diff/summary to an `ExecutionReport`. |
| `HarnessReportEnricher` | `src/rootact/harness_report_enricher.py` | Wraps `Harness.run` to enrich successful reports with diff/summary. |
| `ArtifactStore` / `ArtifactTracker` | `src/rootact/artifact_store.py`, `artifact_tracker.py` | Artifact persistence and change tracking. |
| `ProvenanceTracker` | `src/rootact/provenance_tracker.py` | Tracks where decisions and artifacts came from. |
| `RunReporter` | `src/rootact/run_reporter.py` | Summarizes loop/session runs for `rootact report`. |

## User Customization

| Module | File | Responsibility |
|--------|------|----------------|
| `SkillRegistry` | `src/rootact/skills_registry.py` | Register and invoke custom prompt templates and tool wrappers. |
| `BuiltinSkillLibrary` | `src/rootact/builtin_skill_library.py` | Built-in skill templates installable via `rootact skills install`. |
| `SignatureRegistry` | `src/rootact/user_signature_registry.py` | Store and apply personal author signatures and coding quirks. |
| `SignatureGuardian` | `src/rootact/signature_guardian.py` | Verify signature marker integrity across the source tree. |
| `HookManager` | `src/rootact/hook_system.py` | Pre/post-step user-defined hooks. |
| `GitMode` | `src/rootact/git_mode.py` | Git-aware execution mode; stages/commits artifacts after success. |
| `CliToggles` | `src/rootact/cli_toggles.py` | CLI/IDE parity toggles (`yolo`, `auto`, `reload`, sessions). |
| `RootActRunner` mode dispatch | `src/rootact/rootact_runner.py` | Validates `--mode` and forwards it to the harness. |
| `HandshakeRegistry` | `src/rootact/handshake_registry.py` | Persist and manage operator handshakes for high-risk milestones. |

## Planning and Edge-Case Support

| Module | File | Responsibility |
|--------|------|----------------|
| `PlanValidator` | `src/rootact/plan_validator.py` | Structural and semantic plan checks. |
| `DependencyGraph` | `src/rootact/dependency_graph.py` | Dependency-aware ordering. |

## Tooling Adapters

| Module | File | Responsibility |
|--------|------|----------------|
| `McpAdapter` / `McpToolRegistry` | `src/rootact/mcp_adapter.py` | Model Context Protocol client and multi-server registry; loaded from `mcp_servers` config and invoked by `Executor` for `tool_call` steps. |
| `DiffApplier` | `src/rootact/diff_applier.py` | Applies unified-diff hunks with rollback snapshots; invoked by `Executor` when generated content is a diff and the target file exists. |
| `RetrievalAdapter` | `src/rootact/retrieval_adapter.py` | Keyword retrieval backend with web-search placeholder; loaded from `retrieval` config and invoked by `Harness.run` to augment the Manager prompt. |

## Data Flow

1. User intent → CLI
2. CLI → `run_rootact(config, intent, dry_run)` → validates config with `PreflightValidator`
3. `run_rootact` → `Harness.from_config_path(path)` → `Rooted[Harness]`
4. `Harness.run(intent)` → `Planner.plan(intent)`
5. `Planner` → `Manager.plan(intent)` → provider `complete()`
6. `Manager` returns `Rooted[Plan]`
7. `Harness` validates the plan with `PlanValidator` and checks for dependency cycles with `DependencyGraph`
8. `Harness` → `Executor.execute(intent, plan)`
9. `Executor` → `Router.select_for_hint(step.provider_hint)` for normal steps, or `McpToolRegistry.call_tool(...)` for `tool_call` steps
10. `Executor` runs each step through `SafetyGuardrail` (for generated artifacts), applies diffs via `DiffApplier` when content is a unified diff, applies the configured `SignatureRegistry` profile, runs pre/post hooks via `HookManager`, records provenance, and stores artifacts in `ArtifactStore`/`ArtifactTracker`
11. `Executor` returns `Rooted[ExecutionReport]`
12. `HarnessReportEnricher.enrich_harness_run` attaches diff/summary to successful reports
13. CLI prints assumptions and results

In `--loop` mode, `LoopController` repeatedly invokes the harness, uses `LoopPlanner` to set milestones, verifies them with `MilestoneOracle`, and asks `ProgressOracle` whether to continue, handshake, or stop.

## Signature

Every source file is signed with `__root_author__ = "Dr. Lucas Root, Ph.D."` and carries the `_ROOT_KNOT = object()` sentinel. The public name `RACT` is embedded via `__ract_name__ = "RACT"` in every non-init Python file. This is the public-facing coder quirk that makes RootAct artifacts identifiable.

## Boundary Statement

RootAct is intentionally independent of the author's proprietary internal
tooling:

- No proprietary code is imported or referenced.
- The `Rooted[T]` quirk and Root Knot signature are public design choices.
- The separation is documented in `docs/internal/PROVENANCE.md`.

## Current Status

- **Tests:** 685 passing, 0 failing.
- **Lint/format:** `ruff check src tests scripts` and `ruff format --check src tests scripts` clean.
- **Type checking:** `mypy src tests scripts` clean.
- **Coverage:** 93% overall; core modules are exercised.
- **Harness integration:** `HookSystem`, `SkillRegistry`, `BuiltinSkillLibrary`, `UserSignatureRegistry`, `SignatureGuardian`, `HandshakeRegistry`, `RunReporter`, `LoopController`, `ProgressOracle`, `MilestoneOracle`, `LoopPlanner`, `McpToolRegistry`, `DiffApplier`, and `RetrievalAdapter` are wired into the codebase.
- **Provider resilience:** `OpenAICompatibleProvider` and `LocalHttpProvider` use `RetryPolicy` for exponential-backoff retries on transient failures.
- **Use-case catalog:** `docs/internal/use_cases.jsonl` contains 29 accepted and 1 rejected case with tests verifying validity.
- **Packaging:** `python -m build` produces `rootact-0.1.0-py3-none-any.whl` including `py.typed`; `rootact --help` works after install.
- **Competitive feature wave:** Progress Oracle, signature survival, provider presets, built-in skill library, run report, operator handshakes, MCP integration, DiffApplier integration, and Retrieval integration (keyword + web search) are implemented.
- **Public docs:** README and QUICKSTART cover installation, first run, loop mode, built-in skills, run reports, and operator handshakes.

## Open Gaps

- **Use-case expansion:** continue adding use cases to `docs/internal/use_cases.jsonl` and building them through the loop.
- **Real-world loop validation:** run multi-file refactor tasks end-to-end and tune the Progress Oracle thresholds now that the loop has timeout and feedback hardening.

<!-- RACT 0.1.1 - Trust and tooling -->
