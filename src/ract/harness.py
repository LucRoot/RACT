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
from dataclasses import replace

from ract import config_errors
from ract.codebase_historian import CodebaseHistorian
from ract.config_check import resolve_manager_provider
from ract.contracts.whisperer import WhispererContract
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
from ract.executor.worktree import (
    WorktreeError,
    ensure_git_repo,
)
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
from ract.skills_registry import project_registry
from ract.temperature_router import TemperatureRouter
from ract.planner import Planner
from ract.providers.router import ProviderRouter
from ract.rooted import Rooted
from ract.token_budget import TokenBudget
from ract.workspace_path import is_never_sent
from ract import plan_gate, run_checkpoint, strong_path, turn_context, write_gate
from ract.session_events import plan_event_data


# Files that are eligible for automatic context curation. Binary or noisy
# suffixes are skipped so the token budget is spent on readable project state.
_CONTEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json"}
# RACT control files that describe how to run, not what to build.
_CONTEXT_IGNORE_FILES = {"ract.yaml", "ract.yml", "manager.txt"}
_CONTEXT_IGNORE_DIRS = {
    "__pycache__",
    ".ract",
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
            error=config_errors.config_not_found(path),
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return Rooted(
            value=None,
            assumption=f"Configuration file '{path}' contains valid YAML.",
            confidence=0.0,
            provenance=["harness.load_config"],
            error=config_errors.config_unparsed(exc),
        )
    from ract.config_check import url_credential_problems

    refused = url_credential_problems(raw) if isinstance(raw, dict) else []
    if refused:
        # B-199: an address with a password in it is refused before any
        # provider is built, and the sentence never repeats the address.
        return Rooted(
            value=None,
            assumption="No provider url carries credentials.",
            confidence=0.0,
            provenance=["harness.load_config"],
            error=refused[0],
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
                "model": "local-model",
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
    prompts_dir: str = "prompts",
) -> str:
    """Build a context block of whole files that fit inside the token budget.

    Returns an empty string if no eligible files are found, so the harness
    degrades gracefully on empty or non-code projects.

    RACT's own control files (``ract.yaml``, any ``manager.txt``, the prompts
    directory, ``.ract/``) are never part of the context. LR:: A manager prompt
    that says "reply with ONLY a JSON plan" was being pasted into every
    execution step as if it were project source, and the model obeyed it by
    returning another plan instead of the requested file.
    """
    candidates: list[tuple[Path, float, str]] = []
    prompts_prefix = prompts_dir.strip("/\\").replace("\\", "/") + "/"
    for file_path in project_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _CONTEXT_SUFFIXES:
            continue
        if any(part in _CONTEXT_IGNORE_DIRS for part in file_path.parts):
            continue
        if file_path.name.lower() in _CONTEXT_IGNORE_FILES:
            continue
        try:
            stat = file_path.stat()
            if stat.st_size > 100_000:
                continue
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = file_path.relative_to(project_dir).as_posix()
        # Same rule as every path that sends file content to a model: nothing
        # from .git/ or .ract/ in any letter case, no secret-shaped file.
        if is_never_sent(rel):
            continue
        # Skip the harness's own prompt files; they are handled by Manager.
        if rel.startswith(prompts_prefix) or rel.startswith("prompts/"):
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


def _plan_with_shown_actions(plan: Plan, shown: list) -> Plan:
    """The plan with each step's text replaced by the text the operator approved (L-196 point 1)."""
    if not shown:
        return plan
    approved = {step.n: step.action for step in shown}
    steps = [
        replace(step, action=approved[i])
        if i in approved and approved[i] != step.action
        else step
        for i, step in enumerate(plan.steps, start=1)
    ]
    return replace(plan, steps=steps)


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
        # Repository-supplied hooks, MCP servers and the configured skill are
        # not loaded in an untrusted (headless) run (turn_context).
        untrusted = turn_context.extensions_off()
        self.hook_manager: HookManager | None = (
            None if untrusted else HookManager(hooks_dir)
        )
        self.skills_registry = project_registry(project_dir)
        self.git_mode = GitMode()
        if config.get("git_mode"):
            self.git_mode.enable()
        self.mcp_registry = mcp_registry or McpToolRegistry.from_config(
            {} if untrusted else config
        )
        # Web retrieval sends the operator's intent to an endpoint the
        # repository's ract.yaml names; an untrusted run does not (S-025).
        retrieval_config = config
        if untrusted and (config.get("retrieval") or {}).get("adapter") == "web":
            retrieval_config = {k: v for k, v in config.items() if k != "retrieval"}
        self.retrieval_adapter = retrieval_adapter or _build_retrieval_adapter(
            retrieval_config, project_dir
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
        # B-233 (ADR-0049 D6): the strong-model path reads this; it stays
        # "weak" until a capability cache wires probe facts to it.
        self.model_strength = strong_path.WEAK
        if self.project_dir is not None:
            nb_cfg = config.get("novelty_budget", {})
            self.novelty_budget = NoveltyBudget(
                self.project_dir,
                budget=int(nb_cfg.get("budget", NoveltyBudget.DEFAULT_BUDGET)),
                gravity_top_k=int(nb_cfg.get("gravity_top_k", 10)),
            )
        cg_cfg = config.get("coverage_gate", {})
        # A repository can switch these gates on in its own ract.yaml, and
        # they run its tests or a script from it; not in an untrusted run.
        self.coverage_gate_enabled = (
            bool(cg_cfg.get("enabled", False)) and not untrusted
        )
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
        self.mutation_gate_enabled = (
            bool(mg_cfg.get("enabled", False)) and not untrusted
        )
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
        # B-011a (decision C, D-050): answer steps may read the project with
        # the tier-0 tools, within the budgets in ract.yaml (``agent``).
        self.executor.read_tools = _read_tools_budgets(self.config)
        self.executor.step_tools = _step_tools_budgets(self.config)
        # B-137: with the step agent loop on, a model that answers in prose twice
        # gets the request as one step through the loop.
        self.manager.agent_steps = self.executor.step_tools is not None
        self.executor.grant_root = self.project_dir
        # B-061c (ADR-0049 D14): the per-step review; off unless ract.yaml says.
        self.executor.review_mode = _review_mode(self.config)
        # v0.5.1 wiring module_03 (Lens C C-01) production wire-in.
        # Construct a lightweight SubstrateLoop bound to the project
        # dir and install it on the Executor. This makes every MCP
        # tool_call step (executor/steps.py ~line 890) route through
        # the four-gate chokepoint (manifest, registry, args, budget)
        # in the production run path -- closing the audit's
        # "no production caller" finding at the harness boundary
        # rather than deferring to test-only wiring.
        #
        # The loop's ``wire_mcp_registry`` call inside
        # ``install_substrate_loop`` walks the MCP registry and
        # auto-declares every tool as ``mcp:<qualified_name>`` on
        # the manifest surface. A run with no MCP servers configured
        # gets a zero-tool registry and skips the wire entirely.
        try:
            from ract.executor.loop import SubstrateLoop
            from ract.executor.tool_gate import ToolRegistry

            self.substrate_loop: SubstrateLoop | None = SubstrateLoop(
                repo_root=self.project_dir,
                parent_snapshot="0" * 40,
                tool_registry=ToolRegistry(),
            )
            self.executor.install_substrate_loop(self.substrate_loop)
        except Exception:  # noqa: BLE001
            # Best-effort wire; a broken substrate loop must not
            # crash harness construction. The fallback path in
            # Executor.execute logs + emits a
            # ``tool.invocation.bypassed`` event so the audit
            # surface still catches the gap.
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "harness: substrate_loop install failed; "
                "MCP tool_call will use direct-MCP fallback",
                exc_info=True,
            )
            self.substrate_loop = None

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
        manager_provider, manager_error = resolve_manager_provider(config)
        if manager_provider is None:
            return Rooted(
                value=None,
                assumption="A manager provider is configured in ract.yaml.",
                confidence=0.0,
                provenance=["harness.from_config_path"],
                error=manager_error,
            )
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
        # LR:: Building the registry starts every MCP server (list_all_tools
        # runs each stdio command). This ran before the constructor's
        # untrusted-run check, so a headless run started the repository's MCP
        # servers after all (S-025; the check below was added for it).
        mcp_registry = McpToolRegistry.from_config(
            {} if turn_context.extensions_off() else config
        )
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

    # B-110 D6: asks whether to make a non-repository folder a git repository;
    # set by the runner when someone can answer. None declines.
    git_init_offer: Any = None

    def _offer_git_init(self) -> Rooted[Any] | None:
        """The git init offer (ADR-0047 D6): None when the folder is now a repository.

        LR:: Shown as a tier-2 action with the exact command, the number of
        files and the sensitive names left out. Only the operator's yes runs
        it; with nobody to ask, or on no, nothing is changed and the error
        says how to enable edits later.
        """
        from ract.executor.worktree import INIT_COMMAND, init_preview, init_repository

        assert self.project_dir is not None
        count, left_out = init_preview(self.project_dir)
        offer = self.git_init_offer
        if offer is None or not offer(INIT_COMMAND, count, left_out):
            return _git_init_declined(
                "nobody could answer the offer to make it one"
                if offer is None
                else "you declined `git init`"
            )
        try:
            init_repository(self.project_dir)
        except WorktreeError as exc:
            return _git_init_declined(f"git init did not finish ({exc})")
        print(
            f"note: made this folder a git repository with {count} "
            f"file{'s' if count != 1 else ''} committed"
            + (f"; left out: {', '.join(left_out[:5])}" if left_out else ""),
            flush=True,
        )
        return None

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
        ask: bool = False,
        plan_override: Plan | None = None,
        plan_approval: Callable[["Plan"], Any] | None = None,
        skipped_steps: frozenset[int] = frozenset(),
    ) -> Rooted[ExecutionReport]:
        """Plan and execute the intent.

        With *ask* the planner is skipped: the intent is one answer step,
        which writes nothing (B-042, `/ask` and `ract -p --ask`).

        *plan_approval* is asked once, before the first step, with the plan
        (ADR-0049 D12). It returns None when no question is needed, or a
        ``plan_gate.Resolution``: refused ends the run before any step; approved
        runs the kept steps, skips the others, and answers the per-step
        question for a file the approved plan lists. A resumed run's stored
        plan was approved when it first ran and is not asked again.

        With *plan_override* the planner is skipped and that plan runs: a
        resumed run's stored plan (ADR-0049 D13). It passes the plan
        validator and ``answer_instead`` again, as a new plan would.

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
        context_block = _curate_context(
            self.project_dir,
            intent,
            budget,
            prompts_dir=str(self.config.get("prompts_dir", "prompts")),
        )
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

        skill_name = None if turn_context.extensions_off() else self.config.get("skill")
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

        # module_08 (SUBSTRATE §8): WhispererContract auto-injects a
        # DialectBrief into every planner prompt. Environment-enforced —
        # the planner cannot opt out; the model never sees the pre-
        # injection form. The brief is cached per-snapshot inside the
        # contract (lateral chain branch D from module_06).
        if self.project_dir is not None:
            try:
                contract = WhispererContract(self.project_dir)
                augmented_intent = contract.inject_into_prompt(
                    augmented_intent, snapshot_id=str(self.project_dir)
                )
            except Exception:  # noqa: BLE001 — never fail planning on Whisperer error
                pass

        if plan_override is not None:
            plan_rooted: Rooted[Plan] = Rooted(
                value=plan_override,
                assumption="A resumed run runs the plan it recorded.",
                confidence=1.0,
                provenance=["harness.run", "run_checkpoint"],
            )
        elif ask:
            plan_rooted = Rooted(
                value=Plan(
                    assumption="The user asked a question; the answer is shown "
                    "and no file is written.",
                    confidence=1.0,
                    steps=[
                        Step(action=intent, provider_hint="local", expected_artifact="")
                    ],
                ),
                assumption="An asked question needs no plan.",
                confidence=1.0,
                provenance=["harness.run", "ask"],
            )
        else:
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
        if not plan.planned:
            # B-137: the one step is the user's own request. The planner was
            # given the augmented prompt (dialect brief, context), which the
            # plan showed whole and the step would have carried twice.
            plan = replace(
                plan,
                steps=[
                    replace(step, action=intent) if step.agent else step
                    for step in plan.steps
                ],
            )
        validation = PlanValidator.validate(plan)
        if not validation.is_valid:
            return Rooted(
                value=None,
                assumption="The generated plan passes pre-flight validation.",
                confidence=0.0,
                provenance=["harness.run", "plan_validator.validate"],
                error=f"Plan validation failed: {validation.message}",
            )
        if turn_context.cancelled():
            # The plan arrived after Ctrl-C: run nothing, create no worktree
            # or step branch (G-027).
            return Rooted(
                value=None,
                assumption="The turn was not interrupted before execution began.",
                confidence=0.0,
                provenance=["harness.run"],
                error="Interrupted before execution; nothing was run.",
                hint="interrupted",
            )
        # S-026 follow-up (G-051): a question-like step that names an existing
        # file is answered, not written, decided before any step runs.
        plan, answer_notes = write_gate.answer_instead(plan, self.project_dir)
        for note in answer_notes:
            if turn_context.has_reporter():
                turn_context.report("notice", {"level": "info", "text": note})
            else:
                print(f"note: {note}", flush=True)
        turn_context.report("plan.proposed", plan_event_data(plan))

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

        # Steps the operator skipped before a resumed run (L-196 point 2); a fresh approval replaces them.
        skipped: frozenset[int] = skipped_steps
        # The step the operator named in a fresh ``skip <n>``; a resumed run
        # remembers numbers only, so every skipped step reports "skipped by you".
        skipped_typed: int | None = None
        if plan_approval is not None and plan_override is None:
            outcome = plan_approval(plan)
            if outcome is not None and outcome.kind == "refused":
                if outcome.error:  # nobody could be asked (headless)
                    return Rooted(
                        value=None,
                        assumption="The plan is approved before its first step.",
                        confidence=0.0,
                        provenance=["harness.run", "plan_gate"],
                        error=f"refused: {outcome.error}",
                    )
                return Rooted(
                    value=None,
                    assumption="The plan is approved before its first step.",
                    confidence=0.0,
                    provenance=["harness.run", "plan_gate"],
                    error=plan_gate.CANCELLED,
                    hint="plan_cancelled",
                )
            if outcome is not None:
                skipped = frozenset(step.n for step in outcome.skipped)
                # The named step is the first of the skipped (dependents follow
                # it in plan order); its dependents report the dependency.
                skipped_typed = outcome.skipped[0].n if outcome.skipped else None
                # L-196 point 1: the run takes the text the operator approved, by step number.
                plan = _plan_with_shown_actions(plan, outcome.shown)
                if approval_callback is not None:
                    approval_callback = _approved_plan_callback(
                        approval_callback,
                        {step.target for step in outcome.kept if step.target},
                    )

        # B-233 (ADR-0049 D6): a strong model executes the approved plan as
        # fewer, larger steps; weak keeps the plan exactly as approved (D5).
        # The merge needs the step agent loop, without which a merged step
        # could not run.
        plan = strong_path.apply_strong_path(
            plan,
            strength=strong_path.strength_for_harness(self),
            agent_loop=self.executor.step_tools is not None,
        )
        run_checkpoint.plan_ready(plan)
        if pre_execute_callback is not None:
            pre_execute_callback(plan)
        self.executor.planned_artifacts = frozenset(
            step.expected_artifact for step in plan.steps if step.expected_artifact
        )

        # module_08 (SUBSTRATE §3, Path (d)): route per-plan-step execution
        # through the worktree-per-step SubstrateLoop when the workspace
        # meets the loop's preconditions. Legacy Executor.execute remains
        # the fallback for non-git workspaces, dirty trees, or explicit
        # opt-out via ``substrate_loop: false``. The branch is one call
        # site; Executor internals are unchanged.
        use_substrate = bool(self.config.get("substrate_loop", True))
        substrate_ready = False
        legacy_reason = "substrate_loop is off in ract.yaml"
        if use_substrate and self.project_dir is not None:
            try:
                ensure_git_repo(self.project_dir)
                substrate_ready = True
            except WorktreeError:
                legacy_reason = "this directory is not a git repository"
                plan_writes_files = any(
                    step.expected_artifact and step.tool_call is None
                    for step in plan.steps
                )
                if self.executor.step_tools is not None and plan_writes_files:
                    # B-110 D6: edits need a worktree, so the first change is an
                    # offer to make this folder a repository (tier 2).
                    offered = self._offer_git_init()
                    if offered is not None:
                        return offered
                    substrate_ready = True
        if self.project_dir is not None and not (use_substrate and substrate_ready):
            # LR:: The in-place path has no worktree, no step branch and no
            # rollback point. It used to be taken silently, including after
            # RACT's own edits left the tree dirty (AUD-002). Say so on every
            # run that takes it.
            print(
                f"note: {legacy_reason}; RACT writes directly into your files for "
                "this run (no worktree isolation, no step record).",
                flush=True,
            )
        if use_substrate and substrate_ready:
            # Local import breaks a cycle:
            #   harness → substrate_adapter → core.loop → loop_planner → harness.
            from ract.executor.substrate_adapter import (
                run_via_substrate as _run_via_substrate,
            )

            with plan_gate.skipping(skipped, typed=skipped_typed):
                report_rooted = _run_via_substrate(
                    self,
                    intent,
                    plan,
                    context=context_block,
                    approval_callback=approval_callback,
                    stream=stream,
                    stream_callback=stream_callback,
                ).with_step("harness.run")
        else:
            with plan_gate.skipping(skipped, typed=skipped_typed):
                report_rooted = self.executor.execute(
                    intent,
                    plan,
                    context=context_block,
                    approval_callback=approval_callback,
                    stream=stream,
                    stream_callback=stream_callback,
                ).with_step("harness.run")

        # LR:: The coverage and mutation gates run the project's tests. A plan
        # of answer steps changed nothing for them to measure (B-042).
        plan_writes = any(
            step.expected_artifact or step.tool_call is not None for step in plan.steps
        )
        if plan_writes and self.coverage_gate_enabled and self.project_dir is not None:
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

        if plan_writes and self.mutation_gate_enabled and self.project_dir is not None:
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
                    memory_arena.record("outcome", step_result.outcome(), importance=1)
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


def _approved_plan_callback(
    base: Callable[["Step"], bool], targets: set[str]
) -> Callable[["Step"], bool]:
    """The per-step question, answered yes for a file the approved plan lists (D12).

    An approval covers exactly what the operator saw: a step writing a file
    the plan did not list (or calling a tool) still asks.
    """

    def callback(step: "Step") -> bool:
        if step.tool_call is None and step.expected_artifact in targets:
            return True
        return base(step)

    return callback


def _review_mode(config: dict[str, Any]) -> str:
    """``review`` from ract.yaml; a value config_check reports is treated as off."""
    from ract.review.stage import ReviewConfigError, mode

    try:
        return mode(config)
    except ReviewConfigError as exc:
        print(f"[harness] {exc}; the review stays off", flush=True)
        return "off"


def _read_tools_budgets(config: dict[str, Any]) -> Any:
    """The read-tools loop budgets from ``agent`` in ract.yaml, or None when off.

    ``agent.read_tools: false`` keeps the single completion for answer steps.
    A budget that is not a positive number keeps its default (ADR-0047 D5).
    """
    from ract.tools.loop import LoopBudgets

    raw = config.get("agent")
    agent: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if agent.get("read_tools") is False:
        return None
    defaults = LoopBudgets()

    def number(key: str, default: float) -> float:
        value = agent.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return default
        return value

    return LoopBudgets(
        max_turns=int(number("max_turns", defaults.max_turns)),
        max_tool_calls=int(number("max_tool_calls", defaults.max_tool_calls)),
        max_wall_seconds=float(number("max_wall_seconds", defaults.max_wall_seconds)),
        max_tokens_per_step=int(number("max_tokens_per_step", 0)) or None,
    )


def _git_init_declined(why: str) -> Rooted[Any]:
    return Rooted(
        value=None,
        assumption="This folder is a git repository, or the operator made it one.",
        confidence=0.0,
        provenance=["harness.git_init_offer"],
        error=(
            f"Nothing was changed: this folder is not a git repository and {why}. "
            "RACT edits in a worktree, which needs one."
        ),
        hint=(
            "run `git init` and commit your files, or answer yes to the offer next "
            "time; questions about the code work without it"
        ),
    )


def _step_tools_budgets(config: dict[str, Any]) -> Any:
    """The step agent loop's budgets when ``agent.step_tools`` is true, else None (B-110 D5).

    Off by default until the slice's walkthroughs are done: a write step keeps
    the single completion. The budgets are the read loop's keys in ``agent``.
    """
    raw = config.get("agent")
    agent: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if agent.get("step_tools") is not True:
        return None
    from ract.tools.loop import LoopBudgets

    return (
        _read_tools_budgets({"agent": {**agent, "read_tools": True}}) or LoopBudgets()
    )


# RACT 0.1.1 - Trust and tooling
