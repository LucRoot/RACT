from __future__ import annotations


"""Harness for RACT.

The harness is the user-facing runtime. It loads configuration, instantiates the
router, manager, planner, and executor, and runs an intent end-to-end. Every
operation returns a Rooted result so callers can inspect assumptions.
"""

from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from ract.codebase_historian import CodebaseHistorian
from ract.coverage_delta import (
    gate as coverage_gate,
    save_baseline as save_coverage_baseline,
    save_coverage_badge,
)
from ract.dependency_graph import DependencyGraph
from ract.mutation_runner import run_mutation_tests
from ract.diff_applier import DiffApplier
from ract.duplication_guard import DuplicationGuard
from ract.executor import ExecutionReport, Executor
from ract.git_mode import GitMode
from ract.handshake_registry import HandshakeRegistry
from ract.hook_system import HookManager
from ract.legacy_whisperer import LegacyWhisperer
from ract.manager import Manager, Plan, Step
from ract.memory_arena import MemoryArena
from ract.mcp_adapter import McpToolRegistry
from ract.compression_novelty_detector import CompressionNoveltyDetector
from ract.novelty_budget import NoveltyBudget
from ract.retrieval_adapter import (
    KeywordRetrievalAdapter,
    RetrievalAdapter,
    WebSearchAdapter,
)
from ract.plan_validator import PlanValidator
from ract.skills_registry import SkillRegistry
from ract.temperature_router import TemperatureRouter
from ract.planner import Planner
from ract.providers.router import ProviderRouter
from ract.rooted import Rooted
from ract.token_budget import TokenBudget


# Files that are eligible for automatic context curation. Binary or noisy
# suffixes are skipped so the token budget is spent on readable project state.
_CONTEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json"}
_CONTEXT_IGNORE_DIRS = {
    "__pycache__",
    ".venv",
    ".git",
    "node_modules",
    "_BUILD",
    "htmlcov",
    ".pytest_cache",
    ".ruff_cache",
}


def _default_manager_prompt_path() -> Path:
    """Return the path to the bundled default manager prompt.

    LR:: A fresh project may not have a prompts/manager.txt yet. The bundled
    default lets RACT work out of the box while still allowing users to override
    the prompt by creating their own.
    """
    return Path(str(resources.files("ract") / "default_prompts" / "manager.txt"))


def _load_config(path: Path) -> Rooted[dict[str, Any]]:
    """Load a YAML configuration file."""
    if not path.exists():
        return Rooted(
            value=None,
            assumption=f"Configuration file exists: {path}",
            confidence=0.0,
            provenance=["harness.load_config"],
            error=f"Configuration file not found: {path}",
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return Rooted(
            value=None,
            assumption=f"Configuration file '{path}' contains valid YAML.",
            confidence=0.0,
            provenance=["harness.load_config"],
            error=f"Failed to parse config: {exc}",
        )
    return Rooted(
        value=raw,
        assumption="Configuration file parsed successfully.",
        confidence=1.0,
        provenance=["harness.load_config"],
    )


def _default_config() -> dict[str, Any]:
    return {
        "manager_provider": "local",
        "providers": {
            "local": {
                "adapter": "local_http",
                "url": "http://127.0.0.1:11434/v1",
                "model": "nemotron",
            },
        },
        "prompts_dir": "prompts",
    }


def _build_retrieval_adapter(
    config: dict[str, Any], project_dir: Path
) -> RetrievalAdapter | None:
    """Build a retrieval adapter from config if one is declared.

    Returns None if no retrieval section is present so the harness falls back
    to the existing TokenBudget context curation.
    """
    retrieval = config.get("retrieval")
    if not isinstance(retrieval, dict):
        return None
    adapter_type = retrieval.get("adapter", "keyword")
    if adapter_type == "keyword":
        extensions = tuple(
            retrieval.get(
                "extensions", [".py", ".md", ".txt", ".json", ".yaml", ".yml"]
            )
        )
        return KeywordRetrievalAdapter(project_dir, extensions=extensions)
    if adapter_type == "web":
        return WebSearchAdapter(
            api_key=retrieval.get("api_key"),
            endpoint=retrieval.get("endpoint"),
        )
    # Unknown adapter types are silently ignored; the harness degrades to
    # TokenBudget curation rather than failing init.
    return None


def _context_relevance(path: Path, intent: str) -> float:
    """Score a file by how likely it is to help with the intent.

    LR:: Relevance is intentionally coarse: path-keyword matches plus a small
    bonus for code files. The goal is to surface the right files, not to
    outsmart the model with a perfect ranking.
    """
    name = path.name.lower()
    parts = path.parts
    score = 0.0

    # Intent-keyword matches in the filename.
    intent_words = {w.lower() for w in intent.split() if len(w) > 3}
    if any(word in name for word in intent_words):
        score += 0.5

    # Code files are generally more actionable than logs or lockfiles.
    if "src" in parts or "source" in parts:
        score += 0.25
    if "tests" in parts or "test" in parts:
        score += 0.15
    if name.endswith(".py"):
        score += 0.1

    return min(score, 1.0)


def _curate_context(
    project_dir: Path,
    intent: str,
    max_tokens: int,
) -> str:
    """Build a context block of whole files that fit inside the token budget.

    Returns an empty string if no eligible files are found, so the harness
    degrades gracefully on empty or non-code projects.
    """
    candidates: list[tuple[Path, float, str]] = []
    for file_path in project_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _CONTEXT_SUFFIXES:
            continue
        if any(part in _CONTEXT_IGNORE_DIRS for part in file_path.parts):
            continue
        try:
            stat = file_path.stat()
            if stat.st_size > 100_000:
                continue
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = file_path.relative_to(project_dir).as_posix()
        # Skip the harness's own prompt files; they are handled by Manager.
        if rel.startswith("prompts/"):
            continue
        relevance = _context_relevance(file_path, intent)
        candidates.append((file_path, relevance, content))

    if not candidates:
        return ""

    budget = TokenBudget(max_tokens=max_tokens)
    # Reserve space for the context header/footer and the user's intent.
    overhead = TokenBudget.estimate_tokens("Context:\n\nIntent:\n" + intent)
    if not budget.reserve(overhead):
        return ""

    for file_path, relevance, content in candidates:
        rel = file_path.relative_to(project_dir).as_posix()
        block = f"--- {rel} ---\n{content}\n"
        budget.add_file(rel, block, relevance)

    selected = budget.select()
    if not selected:
        return ""

    return "Context:\n" + "".join(content for _path, content in selected)


class Harness:
    """RACT runtime harness."""

    def __init__(
        self,
        config: dict[str, Any],
        project_dir: Path,
        router: ProviderRouter,
        manager: Manager,
        mcp_registry: McpToolRegistry | None = None,
        retrieval_adapter: RetrievalAdapter | None = None,
        temperature_router: TemperatureRouter | None = None,
        allow_load_bearing_override: bool = False,
        allow_novelty_overrun: bool = False,
        legacy_whisperer: LegacyWhisperer | None = None,
    ) -> None:
        self.config = config
        self.project_dir = project_dir
        self.router = router
        self.manager = manager
        self.temperature_router = temperature_router or TemperatureRouter()
        self.legacy_whisperer = legacy_whisperer
        self.planner = Planner(self.manager)
        hooks_dir = project_dir / ".ract" / "hooks"
        self.hook_manager = HookManager(hooks_dir)
        self.skills_registry = SkillRegistry(project_dir / ".ract")
        self.git_mode = GitMode()
        if config.get("git_mode"):
            self.git_mode.enable()
        self.mcp_registry = mcp_registry or McpToolRegistry.from_config(config)
        self.retrieval_adapter = retrieval_adapter or _build_retrieval_adapter(
            config, project_dir
        )
        self.diff_applier = DiffApplier(self.project_dir)
        self.duplication_guard = None
        if self.project_dir is not None:
            try:
                historian = CodebaseHistorian(self.project_dir).build()
                self.duplication_guard = DuplicationGuard(
                    self.project_dir, historian=historian
                )
            except Exception:  # noqa: BLE001
                # Historian build is best-effort; do not block harness init.
                pass
        self.novelty_budget = None
        if self.project_dir is not None:
            nb_cfg = config.get("novelty_budget", {})
            self.novelty_budget = NoveltyBudget(
                self.project_dir,
                budget=int(nb_cfg.get("budget", NoveltyBudget.DEFAULT_BUDGET)),
                gravity_top_k=int(nb_cfg.get("gravity_top_k", 10)),
            )
        cg_cfg = config.get("coverage_gate", {})
        self.coverage_gate_enabled = bool(cg_cfg.get("enabled", False))
        self.coverage_gate_hard_fail = bool(cg_cfg.get("hard_fail", False))
        self.coverage_gate_timeout = float(cg_cfg.get("timeout", 300.0))
        cg_min = cg_cfg.get("min_percent")
        self.coverage_gate_min_percent = float(cg_min) if cg_min is not None else None
        # Per-file floors let core modules have independent coverage targets while
        # the global floor still applies to the aggregate run.
        self.coverage_gate_per_file: dict[str, float] = {
            str(k).replace("\\", "/"): float(v)
            for k, v in (cg_cfg.get("per_file") or {}).items()
        }
        self.coverage_gate_update_baseline = bool(cg_cfg.get("update_baseline", False))
        badge_path = cg_cfg.get("badge_path")
        self.coverage_gate_badge_path = Path(badge_path) if badge_path else None
        mg_cfg = config.get("mutation_gate", {})
        self.mutation_gate_enabled = bool(mg_cfg.get("enabled", False))
        self.mutation_gate_hard_fail = bool(mg_cfg.get("hard_fail", False))
        self.mutation_gate_timeout = float(mg_cfg.get("timeout", 900.0))
        mg_min = mg_cfg.get("min_score")
        # Baseline measured on src/ract/executor.py (328/686 non-suspicious
        # mutants killed = 47.81%). The default floor is enforced even when no
        # per-file config is present.
        self.mutation_gate_min_score = float(mg_min) if mg_min is not None else 47.81
        # Per-file floors allow core files to have independent targets while the
        # global floor still applies to aggregate runs. Paths are relative to
        # project_dir (e.g. {"src/ract/executor.py": 39.0}).
        self.mutation_gate_per_file: dict[str, float] = {
            str(k): float(v) for k, v in (mg_cfg.get("per_file") or {}).items()
        }
        self.mutation_gate_script_path = mg_cfg.get("script_path")
        self.mutation_gate_wsl_distro = mg_cfg.get("wsl_distro")
        self.compression_novelty_detector = None
        if self.project_dir is not None:
            self.compression_novelty_detector = CompressionNoveltyDetector(
                self.project_dir
            )
        self.handshake_registry = None
        if self.project_dir is not None:
            self.handshake_registry = HandshakeRegistry(self.project_dir)
        self.executor = Executor(
            self.router,
            hook_manager=self.hook_manager,
            project_dir=self.project_dir,
            mcp_registry=self.mcp_registry,
            diff_applier=self.diff_applier,
            duplication_guard=self.duplication_guard,
            temperature_router=self.temperature_router,
            allow_load_bearing_override=allow_load_bearing_override,
            novelty_budget=self.novelty_budget,
            allow_novelty_overrun=allow_novelty_overrun,
            compression_novelty_detector=self.compression_novelty_detector,
            handshake_registry=self.handshake_registry,
        )

    def _run_mutation_gate(
        self, report_rooted: Rooted[ExecutionReport]
    ) -> Rooted[ExecutionReport]:
        """Execute the configured mutation gate and attach scores to the report.

        If ``mutation_gate.per_file`` is configured, each target is mutated
        independently with its matching test file and compared against its own
        floor. Otherwise the global ``mutation_gate.min_score`` floor is applied
        to an aggregate run over the default targets.
        """
        if self.mutation_gate_per_file:
            return self._run_mutation_gate_per_file(report_rooted)
        return self._run_mutation_gate_global(report_rooted)

    def _run_mutation_gate_global(
        self, report_rooted: Rooted[ExecutionReport]
    ) -> Rooted[ExecutionReport]:
        mg_result = run_mutation_tests(
            self.project_dir,
            script_path=self.mutation_gate_script_path,
            timeout=self.mutation_gate_timeout,
            wsl_distro=self.mutation_gate_wsl_distro,
        )
        if not mg_result.is_ok():
            mg_error = mg_result.error or "mutation gate failed"
            if self.mutation_gate_hard_fail:
                return Rooted(
                    value=None,
                    assumption="Mutation gate runs and returns a report.",
                    confidence=0.0,
                    provenance=[
                        "harness.run",
                        "mutation_runner.run_mutation_tests",
                    ],
                    error=f"Mutation gate error: {mg_error}",
                )
            return report_rooted

        mutation_report = mg_result.unwrap()
        if report_rooted.is_ok():
            execution_report = report_rooted.unwrap()
            execution_report.artifacts["mutation_score"] = {
                "score": mutation_report.mutation_score,
                "killed": mutation_report.killed,
                "survived": mutation_report.survived,
                "timeout": mutation_report.timeout,
                "error": mutation_report.error,
                "total": mutation_report.total,
                "min_score": self.mutation_gate_min_score,
            }
            report_rooted = Rooted(
                value=execution_report,
                assumption=report_rooted.assumption,
                confidence=report_rooted.confidence,
                provenance=report_rooted.provenance,
            )
        if mutation_report.mutation_score < self.mutation_gate_min_score:
            mg_msg = (
                f"Mutation gate: score {mutation_report.mutation_score:.2f}% "
                f"is below minimum {self.mutation_gate_min_score:.2f}%."
            )
            if self.mutation_gate_hard_fail:
                return Rooted(
                    value=None,
                    assumption="Mutation score does not fall below the configured floor.",
                    confidence=0.0,
                    provenance=[
                        "harness.run",
                        "mutation_runner.run_mutation_tests",
                    ],
                    error=mg_msg,
                )
        return report_rooted

    def _run_mutation_gate_per_file(
        self, report_rooted: Rooted[ExecutionReport]
    ) -> Rooted[ExecutionReport]:
        failures: list[str] = []
        per_file_scores: dict[str, dict[str, Any]] = {}

        for target, floor in self.mutation_gate_per_file.items():
            target_path = self.project_dir / target
            if not target_path.is_file():
                msg = f"Mutation gate target not found: {target}"
                if self.mutation_gate_hard_fail:
                    return Rooted(
                        value=None,
                        assumption="Mutation gate target file exists.",
                        confidence=0.0,
                        provenance=["harness.run"],
                        error=msg,
                    )
                failures.append(msg)
                continue

            test_file = f"tests/test_{target_path.stem}.py"
            mg_result = run_mutation_tests(
                self.project_dir,
                script_path=self.mutation_gate_script_path,
                timeout=self.mutation_gate_timeout,
                wsl_distro=self.mutation_gate_wsl_distro,
                targets=[target],
                test_runner=f"python3 -m pytest {test_file} -q",
            )
            if not mg_result.is_ok():
                mg_error = mg_result.error or f"mutation gate failed for {target}"
                if self.mutation_gate_hard_fail:
                    return Rooted(
                        value=None,
                        assumption="Per-file mutation gate runs and returns a report.",
                        confidence=0.0,
                        provenance=[
                            "harness.run",
                            "mutation_runner.run_mutation_tests",
                        ],
                        error=f"Mutation gate error for {target}: {mg_error}",
                    )
                failures.append(f"{target}: {mg_error}")
                continue

            mutation_report = mg_result.unwrap()
            per_file_scores[target] = {
                "score": mutation_report.mutation_score,
                "killed": mutation_report.killed,
                "survived": mutation_report.survived,
                "timeout": mutation_report.timeout,
                "error": mutation_report.error,
                "total": mutation_report.total,
                "min_score": floor,
            }
            if mutation_report.mutation_score < floor:
                failures.append(
                    f"{target}: score {mutation_report.mutation_score:.2f}% "
                    f"is below minimum {floor:.2f}%."
                )

        if report_rooted.is_ok():
            execution_report = report_rooted.unwrap()
            execution_report.artifacts["mutation_score_per_file"] = per_file_scores
            report_rooted = Rooted(
                value=execution_report,
                assumption=report_rooted.assumption,
                confidence=report_rooted.confidence,
                provenance=report_rooted.provenance,
            )

        if failures and self.mutation_gate_hard_fail:
            return Rooted(
                value=None,
                assumption="Per-file mutation scores do not fall below configured floors.",
                confidence=0.0,
                provenance=[
                    "harness.run",
                    "mutation_runner.run_mutation_tests",
                ],
                error="Per-file mutation gate failed:\n" + "\n".join(failures),
            )
        return report_rooted

    @classmethod
    def from_config_path(
        cls,
        path: Path,
        *,
        allow_load_bearing_override: bool = False,
        allow_novelty_overrun: bool = False,
    ) -> Rooted["Harness"]:
        """Build a Harness from a YAML config path.

        LR:: Config load/parse failures are surfaced as Rooted errors rather
        than silently falling back to defaults. Callers who want defaults can
        explicitly use _default_config().
        """
        config_rooted = _load_config(path)
        if not config_rooted.is_ok():
            return Rooted(
                value=None,
                assumption="A valid ract.yaml exists and is readable.",
                confidence=0.0,
                provenance=["harness.from_config_path"],
                error=config_rooted.error,
            )

        config = config_rooted.unwrap()
        project_dir = path.parent
        router = ProviderRouter(config.get("providers", {}))
        manager_provider = config.get("manager_provider", "local")
        adapter_rooted = router.get_adapter(manager_provider)
        if not adapter_rooted.is_ok():
            return Rooted(
                value=None,
                assumption=f"Manager provider slot '{manager_provider}' is configured and reachable.",
                confidence=0.0,
                provenance=["harness.from_config_path"],
                error=adapter_rooted.error,
            )

        prompt_path = project_dir / config.get("prompts_dir", "prompts") / "manager.txt"
        if not prompt_path.is_file():
            prompt_path = _default_manager_prompt_path()
        mcp_registry = McpToolRegistry.from_config(config)
        tools_desc = ""
        tools_rooted = mcp_registry.list_all_tools()
        if tools_rooted.is_ok() and tools_rooted.unwrap():
            lines = [
                "Available MCP tools (use tool_call with qualified name server/tool):"
            ]
            for tool in tools_rooted.unwrap():
                lines.append(
                    f"- {tool.get('name')}: {tool.get('description', 'no description')}"
                )
            tools_desc = "\n".join(lines)
        temp_cfg = config.get("temperature", {})
        temperature_router = TemperatureRouter(
            code_temp=float(temp_cfg.get("code", 0.15)),
            plan_temp=float(temp_cfg.get("plan", 0.4)),
            default_temp=float(temp_cfg.get("default", 0.25)),
            brainstorm_temp=float(temp_cfg.get("brainstorm", 0.55)),
        )
        manager_rooted = Manager.from_path(
            adapter_rooted.unwrap(),
            prompt_path,
            tools_description=tools_desc,
            temperature_router=temperature_router,
        )
        if not manager_rooted.is_ok():
            return Rooted(
                value=None,
                assumption="Manager prompt file exists and is readable.",
                confidence=0.0,
                provenance=["harness.from_config_path"],
                error=manager_rooted.error,
            )

        allow_lb_override = allow_load_bearing_override or bool(
            config.get("allow_load_bearing_override", False)
        )
        allow_nb_overrun = allow_novelty_overrun or bool(
            config.get("allow_novelty_overrun", False)
        )

        whisperer = None
        if config.get("legacy_whisperer", {}).get("enabled", False):
            whisperer = LegacyWhisperer(
                project_dir,
                adapter_rooted.unwrap(),
                config=config.get("legacy_whisperer", {}),
            )

        return Rooted(
            value=cls(
                config,
                project_dir,
                router,
                manager_rooted.unwrap(),
                mcp_registry=mcp_registry,
                temperature_router=temperature_router,
                allow_load_bearing_override=allow_lb_override,
                allow_novelty_overrun=allow_nb_overrun,
                legacy_whisperer=whisperer,
            ),
            assumption="Harness initialized from configuration.",
            confidence=1.0,
            provenance=["harness.from_config_path"],
        )

    def _retrieval_block(self, intent: str) -> str:
        """Return a formatted retrieval-results block, or '' if no adapter/results."""
        if self.retrieval_adapter is None:
            return ""
        top_k = int(self.config.get("retrieval", {}).get("top_k", 5))
        results_rooted = self.retrieval_adapter.search(intent, top_k=top_k)
        if not results_rooted.is_ok():
            return ""
        results = results_rooted.unwrap()
        if not results:
            return ""
        lines = ["Retrieved snippets:"]
        for r in results:
            lines.append(f"--- {r.source} (score: {r.score:.3f}) ---")
            lines.append(r.content)
        return "\n".join(lines)

    def run(
        self,
        intent: str,
        *,
        mode: str | None = None,
        pre_execute_callback: Callable[["Plan"], None] | None = None,
        approval_callback: Callable[["Step"], bool] | None = None,
        memory_arena: MemoryArena | None = None,
        stream: bool = False,
        stream_callback: Callable[[str], None] | None = None,
    ) -> Rooted[ExecutionReport]:
        """Plan and execute the intent.

        If *mode* is "documentation", the intent is rewritten to prioritize
        documentation updates. If *mode* is "git", successfully produced
        artifacts are staged and committed after execution.

        *pre_execute_callback* is called after planning/validation and before
        execution. It receives the validated plan and is useful for capturing
        pre-execution snapshots (e.g., session rollback).

        *approval_callback* is forwarded to the executor and is called before
        each step. A False return stops execution and surfaces a Rooted error.

        *memory_arena* is an optional MemoryArena.  When provided, its replay
        block is prepended to the prompt and the outcome of this run is stored
        back into the arena for future sessions.

        *stream* enables streaming completions when the selected provider
        supports it.  *stream_callback* receives each content delta as it
        arrives.
        """
        budget = int(self.config.get("context_budget_tokens", 4096))
        context_block = _curate_context(self.project_dir, intent, budget)
        retrieval_block = self._retrieval_block(intent)
        whisper_block = ""
        if self.legacy_whisperer is not None:
            whisper_rooted = self.legacy_whisperer.brief(intent)
            if whisper_rooted.is_ok():
                whisper_block = whisper_rooted.unwrap()
        memory_block = memory_arena.replay() if memory_arena is not None else ""

        intent_parts: list[str] = []
        if memory_block:
            intent_parts.append(memory_block)
        if context_block:
            intent_parts.append(context_block)
        if retrieval_block:
            intent_parts.append(retrieval_block)
        if whisper_block:
            intent_parts.append(f"Legacy Whisperer brief (cite it):\n{whisper_block}")

        skill_name = self.config.get("skill")
        if skill_name:
            try:
                skill_prompt = self.skills_registry.invoke(
                    skill_name,
                    {
                        "intent": intent,
                        "project_name": self.config.get("project", {}).get("name", ""),
                        "context": context_block or "",
                    },
                )
                intent_parts.append(skill_prompt)
            except Exception:  # noqa: BLE001
                # A missing or broken skill must not block execution.
                pass

        intent_parts.append(f"Intent: {intent}")
        augmented_intent = "\n\n".join(intent_parts)

        plan_rooted = self.planner.plan(augmented_intent)
        if not plan_rooted.is_ok():
            # LR:: The harness contract is Rooted[ExecutionReport]; planning
            # failures must be rewrapped so callers get a consistent type.
            return Rooted(
                value=None,
                assumption="Planning succeeded before execution could begin.",
                confidence=0.0,
                provenance=["harness.run", *(plan_rooted.provenance or [])],
                error=f"Planning failed: {plan_rooted.error}",
            )

        plan = plan_rooted.unwrap()
        validation = PlanValidator.validate(plan)
        if not validation.is_valid:
            return Rooted(
                value=None,
                assumption="The generated plan passes pre-flight validation.",
                confidence=0.0,
                provenance=["harness.run", "plan_validator.validate"],
                error=f"Plan validation failed: {validation.message}",
            )

        dependency_graph = DependencyGraph()
        dependency_graph.add_plan(plan)
        if dependency_graph.has_cycle():
            return Rooted(
                value=None,
                assumption="The generated plan is acyclic.",
                confidence=0.0,
                provenance=["harness.run", "dependency_graph.add_plan"],
                error="Plan contains a dependency cycle; cannot execute.",
            )

        if pre_execute_callback is not None:
            pre_execute_callback(plan)

        report_rooted = self.executor.execute(
            intent,
            plan,
            context=context_block,
            approval_callback=approval_callback,
            stream=stream,
            stream_callback=stream_callback,
        ).with_step("harness.run")

        if self.coverage_gate_enabled and self.project_dir is not None:
            cg_result = coverage_gate(
                self.project_dir,
                timeout=self.coverage_gate_timeout,
                min_percent=self.coverage_gate_min_percent,
                per_file_min_percent=self.coverage_gate_per_file,
            )
            if not cg_result.is_ok():
                cg_error = cg_result.error or "coverage gate failed"
                if self.coverage_gate_hard_fail:
                    return Rooted(
                        value=None,
                        assumption="Coverage gate runs and returns a verdict.",
                        confidence=0.0,
                        provenance=["harness.run", "coverage_delta.gate"],
                        error=f"Coverage gate error: {cg_error}",
                    )
            else:
                delta = cg_result.unwrap()
                if self.coverage_gate_update_baseline and delta.verdict in {
                    "earn",
                    "baseline",
                }:
                    save_coverage_baseline(self.project_dir, delta.after)
                if self.coverage_gate_badge_path is not None:
                    badge_target = self.project_dir / self.coverage_gate_badge_path
                    save_coverage_badge(delta.after, badge_target)
                verdict = delta.verdict
                if verdict in {"regress", "stagnant"} or delta.floor_breached:
                    delta_msg = (
                        f"Coverage gate: {verdict} "
                        f"(current {delta.after.percent_covered:.2f}%, "
                        f"baseline {delta.before.percent_covered:.2f}%, "
                        f"delta {delta.percent_delta:.2f}pp)."
                    )
                    if delta.floor_breached:
                        delta_msg += " Floor breached."
                    if delta.per_file_breaches:
                        delta_msg += " Per-file floor(s) breached."
                    if self.coverage_gate_hard_fail:
                        return Rooted(
                            value=None,
                            assumption="Coverage does not regress, stagnate, or breach floor after execution.",
                            confidence=0.0,
                            provenance=["harness.run", "coverage_delta.gate"],
                            error=delta_msg,
                        )
                    if report_rooted.is_ok():
                        report = report_rooted.unwrap()
                        report.artifacts["coverage_delta"] = {
                            "verdict": delta.verdict,
                            "detail": delta.detail,
                            "floor_breached": delta.floor_breached,
                            "percent_delta": delta.percent_delta,
                            "per_file_breaches": delta.per_file_breaches,
                            "before": {
                                "percent_covered": delta.before.percent_covered,
                                "covered_lines": delta.before.covered_lines,
                                "missing_lines": delta.before.missing_lines,
                                "total_lines": delta.before.total_lines,
                            },
                            "after": {
                                "percent_covered": delta.after.percent_covered,
                                "covered_lines": delta.after.covered_lines,
                                "missing_lines": delta.after.missing_lines,
                                "total_lines": delta.after.total_lines,
                            },
                        }
                        report_rooted = Rooted(
                            value=report,
                            assumption=report_rooted.assumption,
                            confidence=report_rooted.confidence,
                            provenance=report_rooted.provenance,
                        )

        if self.mutation_gate_enabled and self.project_dir is not None:
            report_rooted = self._run_mutation_gate(report_rooted)
            if not report_rooted.is_ok():
                return report_rooted

        if memory_arena is not None:
            memory_arena.record(
                "plan",
                f"assumption={plan.assumption}; confidence={plan.confidence}; "
                f"steps={len(plan.steps)}",
                importance=2,
            )
            if report_rooted.is_ok():
                report = report_rooted.unwrap()
                for step_result in report.step_results:
                    memory_arena.record(
                        "outcome",
                        f"{step_result.step.action} -> "
                        f"{step_result.step.expected_artifact}",
                        importance=1,
                    )
            else:
                memory_arena.record(
                    "failure", f"error={report_rooted.error}", importance=3
                )

        if mode == "git" and report_rooted.is_ok():
            report = report_rooted.unwrap()
            artifact_paths = [
                str(self.project_dir / sr.step.expected_artifact)
                for sr in report.step_results
                if sr.step.expected_artifact
            ]
            self.git_mode.commit_files(artifact_paths, message=f"RACT: {intent[:50]}")

        return report_rooted


# RACT 0.1.1 - Trust and tooling
