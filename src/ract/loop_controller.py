from __future__ import annotations


"""RACT self-recursing build loop.

The LoopController runs a RACT intent repeatedly, verifying each iteration
against two invariants before allowing the next one:

1. Tests pass.
2. The quality score does not regress.
"""

import json
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ract.core.loop import (
    LoopState,
    WorkspaceSnapshot,
    build_loop_state,
    check_t1,
)
from ract.core.predicate import AcceptanceSuite
from ract.error_memory import ErrorMemory
from ract.executor import ExecutionReport
from ract.executor.worktree import ensure_clean_tracked_tree, ensure_git_repo
from ract.gravity_scorer import GravityScorer
from ract.handshake_registry import HandshakeRegistry
from ract.lint_format_repair import LintFormatRepair
from ract.loop_planner import LoopPlanner, Milestone
from ract.manager import Plan
from ract.milestone_oracle import MilestoneContext, MilestoneOracle
from ract.module_family_tracker import (
    build_diversity_prompt,
    classify_milestone,
    detect_tunneling,
)
from ract.preflight_test_validator import PreflightIssue, validate_report_tests
from ract.progress_oracle import MILESTONE_KNOT, ProgressOracle
from ract.quality_scorecard import QualityScorecard
from ract.refactor_ledger import RefactorLedger
from ract.ract_runner import run_ract
from ract.rooted import Rooted
from ract.test_failure_diagnoser import TestFailureDiagnoser


@dataclass(frozen=True)
class LoopIteration:
    """Record of one loop pass."""

    index: int
    intent: str
    report: ExecutionReport | Plan | None
    test_returncode: int | None
    test_summary: str
    test_output: str
    quality_score: float
    reflection: str
    decision: str
    error: str | None = None
    assumptions: list[str] = field(default_factory=list)
    repair_attempt: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    content_snapshot: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LoopResult:
    """Final result of a loop run."""

    iterations: list[LoopIteration]
    final_decision: str
    summary: str
    handshake_milestones: list[str]


class LoopController:
    """Run a RACT intent in a quality-anchored loop.

    The controller delegates each execution to ``run_ract`` and then runs a
    deterministic verification phase. It stops when:

    - ``max_iterations`` is reached,
    - the optional ``done_callback`` returns ``True``,
    - a regression is detected (tests fail or quality drops), or
    - no meaningful change occurs for ``stagnation_limit`` iterations.
    """

    def __init__(
        self,
        config_path: Path | str,
        *,
        max_iterations: int = 10,
        stagnation_limit: int = 3,
        quality_floor: float = 0.0,
        python_executable: str | None = None,
        test_command: str | list[str] | None = None,
        iteration_timeout: float = 900.0,
        planner: LoopPlanner | None = None,
        milestone_oracle: ProgressOracle | None = None,
        handshake_registry: HandshakeRegistry | None = None,
        repair_attempts: int = 0,
        refactor_threshold: float = 3.0,
        allow_debt: bool = False,
        lint_paths: list[str] | None = None,
        tunneling_limit: int = 3,
        strategic_clear_threshold: int = 3,
        allow_load_bearing_override: bool = False,
        allow_novelty_overrun: bool = False,
        acceptance_suite: AcceptanceSuite | None = None,
        run_dir: Path | str | None = None,
        require_git_workspace: bool = False,
        require_clean_tracked_tree: bool = False,
        companion: Any | None = None,
        effort_estimate: Any | None = None,
        iso_perturb: Any | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.max_iterations = max(max_iterations, 1)
        self.stagnation_limit = max(stagnation_limit, 1)
        self.tunneling_limit = max(tunneling_limit, 1)
        self.strategic_clear_threshold = max(strategic_clear_threshold, 1)
        self.quality_floor = quality_floor
        self.python_executable = python_executable or "python"
        if test_command is None:
            self.test_command: list[str] = ["-m", "pytest", "-q", "--tb=no"]
        elif isinstance(test_command, str):
            self.test_command = [test_command]
        else:
            self.test_command = list(test_command)
        self.iteration_timeout = max(iteration_timeout, 0.0)
        self.project_dir = self.config_path.parent
        self.planner = planner
        self.backlog: list[Milestone] | None = None
        self.milestone_oracle = milestone_oracle or MilestoneOracle()
        self.handshake_registry = handshake_registry
        self.handshake_milestones: list[str] = []
        self._completed_families: list[str] = []
        self._rollback_streak: int = 0
        self.repair_attempts_remaining = max(repair_attempts, 0)
        self._repair_intent: str | None = None
        self.refactor_threshold = refactor_threshold
        self.allow_debt = allow_debt
        self.allow_load_bearing_override = allow_load_bearing_override
        self.allow_novelty_overrun = allow_novelty_overrun
        self._refactor_ledger = RefactorLedger(
            project_dir=self.project_dir,
            threshold=self.refactor_threshold,
        )
        if self.allow_debt:
            self._refactor_ledger.allow_debt("operator passed --allow-debt")
        self._gravity_scorer = GravityScorer(self.project_dir)
        self._previous_snapshot: dict[str, str] = {}
        self._baseline_snapshot: dict[str, str] = {}
        self._snapshot_initialized: bool = False
        self._failure_diagnoser = TestFailureDiagnoser(
            self.project_dir,
            python_executable=self.python_executable,
            test_command=self.test_command,
        )
        self._lint_repair = LintFormatRepair(
            self.project_dir,
            python_executable=self.python_executable,
            paths=lint_paths,
        )
        self._error_memory = ErrorMemory(self.project_dir)

        # ------------------------------------------------------------------
        # Substrate wiring (SUBSTRATE §2, lateral chain branch E)
        # ------------------------------------------------------------------
        # When an ``AcceptanceSuite`` is provided the loop routes through
        # ``build_loop_state`` (module_01), which persists the suite to
        # ``run_dir/suite.json`` before returning a ``LoopState``. T1 then
        # reads from ``state.suite`` rather than the milestone oracle path;
        # the milestone oracle survives here only as a scheduling heuristic
        # and, when a suite is present, is not consulted for termination.
        self.acceptance_suite: AcceptanceSuite | None = acceptance_suite
        self.run_dir: Path | None = Path(run_dir) if run_dir else None
        self._loop_state: LoopState | None = None
        # Loop-entry preconditions (lateral chain branch E). Off by default
        # so v0.3 CLI paths keep working; turned on by the substrate CLI
        # path and by tests that assert the git-workspace / clean-tree
        # invariants.
        if require_git_workspace:
            ensure_git_repo(self.project_dir)
        if require_clean_tracked_tree:
            ensure_clean_tracked_tree(self.project_dir)

        # ------------------------------------------------------------------
        # ALM module_04 wiring (G7 companion + G8 effort reconciliation).
        # ------------------------------------------------------------------
        # ``companion`` is a bundle carrying the companion adapter, config,
        # runner, and recent-history reader. When None the loop runs the
        # substrate path unchanged. When present, T1 fires G7 after the
        # predicate check succeeds; surviving findings queue a resume
        # intent and emit ``laziness.violated``.
        # ``effort_estimate`` is the pre-loop static-heuristic estimate
        # (``ract.antilazy.effort.EffortEstimate``); the loop measures
        # realized effort on T1 completion and refuses to terminate
        # COMPLETE while anomalies remain (G8).
        self.companion = companion
        self.effort_estimate = effort_estimate
        self._recent_provider_history: tuple[str, ...] = ()
        self._effort_suspicion_active: bool = False
        self._companion_findings_seen: int = 0

        # ------------------------------------------------------------------
        # ALM module_06 wiring (isomorphic-perturbation gate).
        # ------------------------------------------------------------------
        # ``iso_perturb`` is an ``IsoPerturbBundle`` (typed at runtime by
        # ``ract.antilazy.iso_perturb``) carrying the primary solution
        # producer, optional companion, tunables, workspace symbols to
        # preserve on rename, and the report-write directory. When None
        # the substrate + module_04 paths run unchanged. When present,
        # the loop runs the gate on completion but only fires it when
        # ``detect_rule_like_intent(iteration.intent).is_rule_like`` is
        # True. Divergence blocks COMPLETE and queues a resume prompt.
        self.iso_perturb = iso_perturb

    def _take_snapshot(self) -> dict[str, str]:
        """Return a snapshot of Python file contents relative to project_dir."""
        snapshot: dict[str, str] = {}
        if not self.project_dir.is_dir():
            return snapshot
        for path in self.project_dir.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = str(path.relative_to(self.project_dir))
            try:
                snapshot[rel] = path.read_text(encoding="utf-8")
            except OSError:
                continue
        return snapshot

    def _update_refactor_ledger(self) -> None:
        """Compare current project state to the previous snapshot and record deltas."""
        current = self._take_snapshot()
        changes: dict[str, tuple[str | None, str | None]] = {}
        for path in set(self._previous_snapshot) | set(current):
            old = self._previous_snapshot.get(path)
            new = current.get(path)
            if old != new:
                changes[path] = (old, new)
        if changes:
            self._refactor_ledger.record_file_changes(changes)
            self._refactor_ledger.save()
        self._previous_snapshot = current

    def _ledger_breach_message(self) -> str | None:
        """Return a message if the refactor ledger blocks completion, else None."""
        if not self._refactor_ledger.is_breach():
            return None
        data = self._refactor_ledger.to_dict()
        return (
            f"Refactor tax breach: added {data['lines_added']} lines, "
            f"maintained {data['maintained_lines']} lines "
            f"(ratio {data['ratio']} > threshold {data['threshold']}). "
            "Pass --allow-debt to complete pure feature additions."
        )

    def _detect_intent_oscillation(
        self,
        current_snapshot: dict[str, str],
        iterations: list[LoopIteration],
    ) -> bool:
        """Return True if the project has returned to its baseline state.

        A passing iteration that exactly matches the baseline after at least one
        earlier iteration diverged from it means the loop undid its own work.
        This is a stronger signal than stagnation: it is an A->B->A oscillation.
        """
        if not self._baseline_snapshot:
            return False
        if current_snapshot == self._baseline_snapshot:
            # Require evidence that the loop actually left baseline at some point.
            for it in iterations:
                if it.content_snapshot != self._baseline_snapshot:
                    return True
        return False

    def run(
        self,
        intent: str,
        *,
        done_callback: Callable[[LoopIteration], bool] | None = None,
    ) -> LoopResult:
        """Run the loop and return the final result."""
        if self.planner is not None and self.backlog is None:
            self.backlog = self._load_or_generate_backlog(intent)

        # Substrate wiring (SUBSTRATE §2, module_01 predicate-based T1):
        # when an ``AcceptanceSuite`` is on the controller, build the
        # ``LoopState`` up-front so the suite is persisted to
        # ``run_dir/suite.json`` before step 1 runs, and wrap
        # ``done_callback`` so termination is decided by the predicate
        # suite rather than by the milestone-oracle path.
        if self.acceptance_suite is not None:
            plan_seed = Plan(assumption=intent, confidence=1.0, steps=[])
            snapshot_seed = WorkspaceSnapshot(
                files=dict(self._take_snapshot()), timestamp=0.0
            )
            self._loop_state = build_loop_state(
                plan=plan_seed,
                workspace=snapshot_seed,
                suite=self.acceptance_suite,
                run_dir=self.run_dir,
                handshake_registry=self.handshake_registry,
            )
            user_done = done_callback
            done_callback = self._make_suite_done_callback(user_done)

        iterations: list[LoopIteration] = []
        previous_score: float | None = None
        stagnation_count = 0

        for index in range(1, self.max_iterations + 1):
            current_milestone = self._current_milestone()
            if current_milestone is None and self.backlog is not None:
                return LoopResult(
                    iterations=iterations,
                    final_decision="done",
                    summary="All milestones completed.",
                    handshake_milestones=list(self.handshake_milestones),
                )

            iteration_intent = self._augment_intent(
                intent, iterations, current_milestone
            )

            # Capture the project state before this iteration writes anything.
            if not self._snapshot_initialized:
                self._baseline_snapshot = self._take_snapshot()
                self._previous_snapshot = dict(self._baseline_snapshot)
                self._snapshot_initialized = True

            result = self._run_with_timeout(iteration_intent)

            report = result.unwrap() if result.is_ok() else None
            error = result.error if not result.is_ok() else None
            assumptions: list[str] = []
            if isinstance(report, ExecutionReport):
                assumptions = list(report.assumptions)
            elif isinstance(report, Plan):
                assumptions = [report.assumption]

            preflight_issues = self._preflight_validate_tests(report)
            if preflight_issues:
                if self.repair_attempts_remaining > 0:
                    self.repair_attempts_remaining -= 1
                    self._repair_intent = self._build_preflight_repair_prompt(
                        preflight_issues
                    )
                    iteration = LoopIteration(
                        index=index,
                        intent=iteration_intent,
                        report=report,
                        test_returncode=None,
                        test_summary="preflight validation failed",
                        test_output=self._format_preflight_issues(preflight_issues),
                        quality_score=self._compute_quality_score(report),
                        reflection=self._reflect(
                            index,
                            error,
                            None,
                            self._compute_quality_score(report),
                            previous_score,
                        ),
                        decision="continue",
                        error=error,
                        assumptions=assumptions,
                        repair_attempt=True,
                        metrics=(
                            report.metrics
                            if isinstance(report, ExecutionReport)
                            else {}
                        ),
                        content_snapshot=dict(self._previous_snapshot),
                    )
                    iterations.append(iteration)
                    continue
                return LoopResult(
                    iterations=iterations,
                    final_decision="regression",
                    summary=self._format_preflight_issues(preflight_issues),
                    handshake_milestones=list(self.handshake_milestones),
                )

            test_returncode, test_summary, test_output = self._run_tests()
            quality_score = self._compute_quality_score(report)
            self._update_refactor_ledger()
            ledger_message = self._ledger_breach_message()
            current_snapshot = dict(self._previous_snapshot)

            reflection = self._reflect(
                index,
                error,
                test_returncode,
                quality_score,
                previous_score,
                ledger_message,
            )

            metrics = report.metrics if isinstance(report, ExecutionReport) else {}

            iteration = LoopIteration(
                index=index,
                intent=iteration_intent,
                report=report,
                test_returncode=test_returncode,
                test_summary=test_summary,
                test_output=test_output,
                quality_score=quality_score,
                reflection=reflection,
                decision="pending",
                error=error,
                assumptions=assumptions,
                metrics=metrics,
                content_snapshot=current_snapshot,
            )

            if self._detect_intent_oscillation(current_snapshot, iterations):
                decision = "regression"
            else:
                decision = self._decide(
                    iteration,
                    stagnation_count,
                    done_callback,
                    iterations[-1] if iterations else None,
                )

            # Replace the pending placeholder with the real decision.
            iteration = LoopIteration(
                index=iteration.index,
                intent=iteration.intent,
                report=iteration.report,
                test_returncode=iteration.test_returncode,
                test_summary=iteration.test_summary,
                test_output=iteration.test_output,
                quality_score=iteration.quality_score,
                reflection=iteration.reflection,
                decision=decision,
                error=iteration.error,
                assumptions=iteration.assumptions,
                repair_attempt=iteration.repair_attempt,
                metrics=iteration.metrics,
                content_snapshot=iteration.content_snapshot,
            )
            iterations.append(iteration)
            self._error_memory.record(iteration)

            if decision == "stagnant":
                self._rollback_streak += 1
            elif decision in {"done", "continue"}:
                self._rollback_streak = 0

            if (
                decision == "stagnant"
                and self._rollback_streak >= self.strategic_clear_threshold
            ):
                self._error_memory.clear()
                self._rollback_streak = 0
                stagnation_count = 0
                self._repair_intent = self._build_strategic_clear_intent(
                    decision, index, intent
                )
                continue

            if decision in {"done", "stop", "regression"}:
                return LoopResult(
                    iterations=iterations,
                    final_decision=decision,
                    summary=self._summarize(iterations),
                    handshake_milestones=list(self.handshake_milestones),
                )

            if decision == "stagnant":
                stagnation_count += 1
                if stagnation_count >= self.stagnation_limit:
                    return LoopResult(
                        iterations=iterations,
                        final_decision="stop",
                        summary=(
                            f"Stopped after {index} iterations; no meaningful "
                            f"progress for {self.stagnation_limit} iterations."
                        ),
                        handshake_milestones=list(self.handshake_milestones),
                    )
            else:
                stagnation_count = 0
                if self.backlog is not None and current_milestone is not None:
                    oracle_result = self.milestone_oracle.evaluate(
                        {
                            "milestone_context": MilestoneContext(
                                milestone=current_milestone,
                                report=report,
                                test_returncode=test_returncode,
                                project_dir=self.project_dir,
                            )
                        }
                    )
                    if not oracle_result.is_ok():
                        return LoopResult(
                            iterations=iterations,
                            final_decision="regression",
                            summary=f"Milestone oracle failed: {oracle_result.error}",
                            handshake_milestones=list(self.handshake_milestones),
                        )
                    verdict = oracle_result.unwrap()
                    if verdict.knot is not MILESTONE_KNOT:
                        return LoopResult(
                            iterations=iterations,
                            final_decision="regression",
                            summary="Milestone verdict missing canonical milestone sentinel.",
                            handshake_milestones=list(self.handshake_milestones),
                        )
                    if verdict.verdict in {"proceed", "handshake"}:
                        self.backlog = LoopPlanner.mark_done(
                            self.backlog, current_milestone.id
                        )
                        self._completed_families.append(
                            classify_milestone(current_milestone)
                        )
                        if verdict.verdict == "handshake":
                            self.handshake_milestones.append(current_milestone.id)
                            if self.handshake_registry is not None:
                                self.handshake_registry.add(
                                    current_milestone.id,
                                    current_milestone.description,
                                    current_milestone.acceptance,
                                )
                        self._save_backlog()
                    elif verdict.verdict == "stop":
                        return LoopResult(
                            iterations=iterations,
                            final_decision="stop",
                            summary=f"Milestone oracle stopped the loop: {verdict.reason}",
                            handshake_milestones=list(self.handshake_milestones),
                        )
                    # verdict == "retry" leaves the milestone open.

            previous_score = quality_score

        return LoopResult(
            iterations=iterations,
            final_decision="stop",
            summary=f"Reached max iterations ({self.max_iterations}).",
            handshake_milestones=list(self.handshake_milestones),
        )

    def _make_suite_done_callback(
        self,
        user_done: Callable[[LoopIteration], bool] | None,
    ) -> Callable[[LoopIteration], bool]:
        """Wrap ``done_callback`` so the acceptance suite is T1's authority.

        The wrapped callback refreshes the ``LoopState.workspace`` snapshot
        against the current on-disk project state, calls ``check_t1``, and
        returns ``True`` only when every required predicate is ``ok``. A
        user-supplied ``done_callback`` still fires — it is AND-ed with the
        suite result so callers can add extra done-signals without being
        able to *soften* the environment gate (SUBSTRATE §11 signal 1).

        ALM module_04: after T1 fires, run the completion-path gates
        (G7 companion + G8 effort reconciliation). If either gate blocks
        completion, queue the resume prompt into the next iteration and
        return False (loop does not terminate COMPLETE).
        """

        def _cb(iteration: LoopIteration) -> bool:
            state = self._loop_state
            if state is None:
                return bool(user_done(iteration)) if user_done else False
            # Refresh the snapshot to reflect the current on-disk state so
            # the predicate evaluators see what the loop just wrote.
            state.workspace = WorkspaceSnapshot(
                files=dict(self._take_snapshot()),
                timestamp=float(iteration.index),
                metadata=dict(state.workspace.metadata),
            )
            cause = check_t1(state.suite, state.workspace)
            suite_done = cause is not None
            user_cb_result = True
            if user_done is not None:
                user_cb_result = bool(user_done(iteration))
            if not suite_done:
                return False
            # ALM module_04: G7 + G8 completion-path gates. Only run
            # when either was configured; otherwise substrate behaviour
            # is preserved.
            if self.companion is not None or self.effort_estimate is not None:
                gate_outcome = self._run_completion_gates(iteration)
                if gate_outcome is not None and gate_outcome.blocks_complete:
                    # Queue the resume prompt for the next iteration —
                    # `_augment_intent` prepends `_repair_intent` verbatim
                    # so the primary sees the gate feedback.
                    if gate_outcome.resume_prompt:
                        self._repair_intent = gate_outcome.resume_prompt
                    return False
            # ALM module_06: iso-perturbation gate. Fires only when the
            # detector flags the intent as rule-like; skipped otherwise.
            if self.iso_perturb is not None:
                iso_outcome = self._run_iso_perturb_gate(iteration)
                if iso_outcome is not None and iso_outcome.blocks_complete:
                    if iso_outcome.resume_prompt:
                        self._repair_intent = iso_outcome.resume_prompt
                    return False
            return user_cb_result if user_done is not None else True

        return _cb

    def _run_completion_gates(self, iteration: LoopIteration):
        """Invoke ALM module_04's completion-path gates.

        Kept as a method so tests can monkeypatch it and so the
        substrate loop does not import ALM at module load time. Returns
        a ``CompletionGateOutcome`` or ``None`` when neither G7 nor G8
        was configured.
        """
        if self.companion is None and self.effort_estimate is None:
            return None
        from ract.antilazy.completion_gate import run_completion_gates

        state = self._loop_state
        visible_suite = state.suite if state is not None else None
        # A DualAcceptanceSuite exposes ``.visible``; a plain
        # AcceptanceSuite is its own visible half.
        if visible_suite is not None and hasattr(visible_suite, "visible"):
            visible_suite = visible_suite.visible

        # Extract a Patch from the iteration if one is present. In the
        # substrate v0.4 shape the ExecutionReport does not directly
        # produce a Patch; callers passing an effort_estimate typically
        # inject the diff via the `companion.final_diff_provider`
        # callback (see completion_gate docstring). Tests inject the
        # patch through the `_final_diff_for_gates` hook below.
        final_diff = self._final_diff_for_gates(iteration)
        if final_diff is None or visible_suite is None:
            return None

        return run_completion_gates(
            intent=iteration.intent,
            final_diff=final_diff,
            visible_suite=visible_suite,
            companion_bundle=self.companion,
            effort_estimate=self.effort_estimate,
            pre_change_workspace=self._pre_change_workspace_for_gates(),
            post_change_workspace=self._post_change_workspace_for_gates(),
        )

    def _run_iso_perturb_gate(self, iteration: LoopIteration):
        """Invoke ALM module_06's iso-perturbation gate.

        Kept as a method so tests can monkeypatch it and so the
        substrate loop does not import ALM at module load time.
        Returns an ``IsoPerturbGateOutcome`` or ``None`` when the
        bundle was not configured. The gate itself internally checks
        rule-like detection and returns ``blocks_complete=False`` for
        non-rule-like intents so this method's caller does not need
        to re-check.
        """
        if self.iso_perturb is None:
            return None
        from ract.antilazy.iso_perturb import run_iso_perturb_gate

        state = self._loop_state
        workspace = state.workspace if state is not None else None
        if workspace is None:
            return None
        original_solution = self._iso_perturb_original_solution(iteration)
        run_id = self.run_dir.name if self.run_dir is not None else None
        return run_iso_perturb_gate(
            intent=iteration.intent,
            workspace=workspace,
            original_solution=original_solution,
            bundle=self.iso_perturb,
            run_id=run_id,
        )

    def _iso_perturb_original_solution(
        self, iteration: LoopIteration
    ) -> str | None:
        """Return the original solution text for the iso-perturbation gate.

        Overridden by tests. Default reads ``iteration.metrics`` for a
        ``"solution_text"`` entry the executor may have stashed there.
        Substrate v0.4 does not emit a canonical solution string; a
        follow-up (module_08 CLI migration) will wire this to the
        executor's diff-and-plan-text emitter. Until then the hook
        makes the gate testable without stubbing the entire executor.
        """
        if isinstance(iteration.metrics, dict):
            candidate = iteration.metrics.get("solution_text")
            if isinstance(candidate, str) and candidate:
                return candidate
        return None

    def _final_diff_for_gates(self, iteration: LoopIteration):
        """Return the final diff (``Patch``) for the completion gates.

        Overridden by tests. Default returns ``None`` (gates skipped).
        The substrate v0.4 executor does not yet produce a ``Patch``
        object; a follow-up module (module_08 CLI migration) will wire
        this to the executor's diff-emitter. Until then the hook makes
        the gates testable without stubbing the entire executor.
        """
        return None

    def _pre_change_workspace_for_gates(self):
        """Return the pre-change workspace for the runner (test hook)."""
        return self._baseline_snapshot

    def _post_change_workspace_for_gates(self):
        """Return the post-change workspace for the runner (test hook)."""
        return self._previous_snapshot

    @property
    def loop_state(self) -> LoopState | None:
        """The ``LoopState`` constructed at ``run()`` when a suite is set.

        Tests read ``controller.loop_state.suite`` to assert T1 is being
        driven by the suite substrate rather than the milestone oracle.
        """
        return self._loop_state

    def _load_or_generate_backlog(self, intent: str) -> list[Milestone] | None:
        """Load an existing backlog or ask the management LM to create one."""
        assert self.planner is not None
        existing = self.planner.load()
        if existing is not None:
            return existing
        rooted = self.planner.generate_backlog(intent)
        if not rooted.is_ok():
            return None
        backlog = rooted.unwrap()
        self.planner.save(backlog)
        return backlog

    def _current_milestone(self) -> Milestone | None:
        """Return the next open milestone, if a backlog is active."""
        if self.backlog is None:
            return None
        return LoopPlanner.next_open(self.backlog)

    def _save_backlog(self) -> None:
        """Persist the current backlog, if any."""
        if self.planner is not None and self.backlog is not None:
            self.planner.save(self.backlog)

    def _preflight_validate_tests(
        self, report: ExecutionReport | Plan | None
    ) -> list[PreflightIssue]:
        """Catch mechanical test defects before invoking pytest.

        LR:: A generated test with a syntax error or a missing ``import re``
        should not waste a full pytest call. The validator inspects the content
        the model produced, not the file on disk, so it catches problems even
        if the Executor has not yet written the artifact.
        """
        if not isinstance(report, ExecutionReport):
            return []
        return validate_report_tests(report)

    def _format_preflight_issues(self, issues: list[PreflightIssue]) -> str:
        """Return a concise, machine-readable description of preflight issues."""
        return "\n".join(f"{issue.path}: {issue.message}" for issue in issues)

    def _build_preflight_repair_prompt(self, issues: list[PreflightIssue]) -> str:
        """Construct a repair intent targeting the reported preflight defects."""
        details = self._format_preflight_issues(issues)
        return (
            f"[PREFLIGHT REPAIR - generated test artifact(s) failed mechanical "
            f"validation; {self.repair_attempts_remaining} attempt(s) remaining]\n\n"
            "Fix the following mechanical defects in the generated test file(s) "
            "and return only the corrected file(s). Do not change source files.\n"
            f"{details}"
        )

    def _build_strategic_clear_intent(
        self, last_decision: str, index: int, original_intent: str
    ) -> str:
        """Return a reset intent after a rollback streak.

        LR:: When the loop hits the same wall repeatedly, the cheapest recovery is
        to clear noisy memory (especially failure patterns) and restate the goal
        with an explicit instruction to try a different path.
        """
        return (
            f"[STRATEGIC CONTEXT CLEAR - iteration {index} ended with "
            f"'{last_decision}' for {self.strategic_clear_threshold} consecutive "
            "stagnant iterations. Error memory has been cleared.]\n\n"
            "Return to the original goal and constraints, ignore the previous "
            "stuck approach, and choose a materially different strategy.\n\n"
            f"Original intent: {original_intent}"
        )

    def _run_with_timeout(self, intent: str) -> Rooted[ExecutionReport | Plan]:
        """Call ``run_ract`` in a thread and enforce ``iteration_timeout``.

        LR:: A hung provider call must not stall the loop. Running each iteration
        in its own thread lets us cap wall-clock time and return a Rooted timeout
        failure instead of waiting forever.
        """
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                run_ract,
                self.config_path,
                intent,
                yolo=True,
                allow_load_bearing_override=self.allow_load_bearing_override,
                allow_novelty_overrun=self.allow_novelty_overrun,
            )
            try:
                return future.result(timeout=self.iteration_timeout)
            except TimeoutError:
                return Rooted(
                    value=None,
                    assumption=(
                        "A single loop iteration completes within the configured timeout."
                    ),
                    confidence=0.0,
                    provenance=["loop_controller._run_with_timeout"],
                    error=f"Iteration timed out after {self.iteration_timeout}s.",
                )

    def _format_backlog(self) -> str:
        """Return a human-readable summary of the backlog."""
        if self.backlog is None:
            return ""
        lines: list[str] = ["Current backlog:"]
        for milestone in self.backlog:
            marker = "[x]" if milestone.status == "done" else "[ ]"
            lines.append(f"{marker} {milestone.id}: {milestone.description}")
        return "\n".join(lines)

    def _augment_intent(
        self,
        intent: str,
        iterations: list[LoopIteration],
        current_milestone: Milestone | None,
    ) -> str:
        """Prepend loop memory, backlog, and current milestone to the intent."""
        if self._repair_intent is not None:
            repair = self._repair_intent
            self._repair_intent = None
            return repair

        parts: list[str] = []
        if self.backlog is not None:
            parts.append(self._format_backlog())
        if current_milestone is not None:
            parts.append(
                "Current milestone to complete in this iteration:\n"
                f"  id: {current_milestone.id}\n"
                f"  description: {current_milestone.description}\n"
                f"  acceptance: {current_milestone.acceptance}"
            )
        if iterations:
            last = iterations[-1]
            memory = (
                f"[Loop memory: iteration {last.index} ended with decision="
                f"'{last.decision}', quality_score={last.quality_score}, "
                f"tests_passed={last.test_returncode == 0}. "
                f"Reflection: {last.reflection}]"
            )
            parts.append(memory)

            feedback_parts: list[str] = []
            if last.error:
                feedback_parts.append(f"execution error: {last.error}")
            if last.test_summary:
                feedback_parts.append(f"test summary: {last.test_summary}")
            if feedback_parts:
                parts.append(
                    "[Previous iteration feedback]\n"
                    + "\n".join(f"- {part}" for part in feedback_parts)
                )
        signal = detect_tunneling(self._completed_families, self.tunneling_limit)
        if signal is not None:
            parts.append(build_diversity_prompt(signal, self.project_dir))

        error_summary = self._error_memory.summarize()
        if error_summary:
            parts.append(
                "[Error memory: avoid repeating these recent failure patterns]\n"
                f"{error_summary}"
            )

        if not parts:
            return intent
        return "\n\n".join(parts) + f"\n\n{intent}"

    def _run_tests(self) -> tuple[int | None, str, str]:
        """Run the project's test suite and return (returncode, summary, full_output)."""
        try:
            proc = subprocess.run(
                [self.python_executable, *self.test_command],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None, "test runner unavailable or timed out", ""
        full_output = (proc.stdout or "") + (proc.stderr or "")
        summary = full_output.strip().splitlines()[-1] if full_output else ""
        return proc.returncode, summary, full_output

    def _compute_quality_score(self, report: ExecutionReport | Plan | None) -> float:
        """Return the deterministic quality score for the iteration."""
        scorecard = QualityScorecard()
        if isinstance(report, Plan):
            return scorecard.compute_score(report)
        if isinstance(report, ExecutionReport):
            return scorecard.compute_score(report.plan)
        return 0.0

    def _reflect(
        self,
        index: int,
        error: str | None,
        test_returncode: int | None,
        quality_score: float,
        previous_score: float | None,
        ledger_message: str | None = None,
    ) -> str:
        """Produce a human-readable reflection on the iteration."""
        parts: list[str] = []
        if error:
            parts.append(f"execution failed: {error}")
        elif test_returncode is None:
            parts.append("tests could not be run")
        elif test_returncode != 0:
            parts.append("tests failed")
        else:
            parts.append("tests passed")

        if previous_score is not None:
            delta = round(quality_score - previous_score, 3)
            direction = (
                "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged"
            )
            parts.append(
                f"quality score {direction} ({previous_score} -> {quality_score})"
            )
        else:
            parts.append(f"quality score {quality_score}")

        if ledger_message:
            parts.append(f"refactor ledger: {ledger_message}")

        return f"Iteration {index}: " + "; ".join(parts) + "."

    def _report_fingerprint(
        self, report: ExecutionReport | Plan | None
    ) -> tuple[tuple[str, str], ...] | None:
        """Return a stable, comparable fingerprint of generated artifact content.

        LR:: Two iterations are only truly identical if they produce the same
        artifact content. Comparing scores and filenames alone flags progress as
        stagnant when a model keeps improving the same file but the score hasn't
        moved yet.
        """
        if not isinstance(report, ExecutionReport):
            return None
        pairs: list[tuple[str, str]] = []
        for step_result in report.step_results:
            artifact = step_result.step.expected_artifact
            if artifact:
                pairs.append((artifact, step_result.content))
        return tuple(sorted(pairs))

    def _decide(
        self,
        iteration: LoopIteration,
        stagnation_count: int,
        done_callback: Callable[[LoopIteration], bool] | None,
        last_iteration: LoopIteration | None,
    ) -> str:
        """Return the next decision: continue, done, stop, regression, or stagnant."""
        if iteration.report is None:
            return "regression"
        if iteration.test_returncode is not None and iteration.test_returncode != 0:
            if self._attempt_repair(iteration):
                return "continue"
            return "regression"
        if iteration.quality_score < self.quality_floor:
            return "regression"

        if self._attempt_lint_repair():
            return "continue"

        if last_iteration is not None:
            previous_score = last_iteration.quality_score
            if iteration.quality_score < previous_score:
                return "regression"
            same_score = iteration.quality_score == previous_score
            same_content = self._report_fingerprint(
                iteration.report
            ) == self._report_fingerprint(last_iteration.report)
            if same_score and same_content:
                return "stagnant"

        if done_callback is not None and done_callback(iteration):
            ledger_message = self._ledger_breach_message()
            if ledger_message:
                return "stop"
            return "done"

        if iteration.index >= self.max_iterations:
            return "stop"

        return "continue"

    def _attempt_repair(self, iteration: LoopIteration) -> bool:
        """Diagnose test failures and queue a repair intent if attempts remain."""
        if self.repair_attempts_remaining <= 0:
            return False
        if not iteration.test_output:
            return False

        rooted = self._failure_diagnoser.diagnose(iteration.test_output)
        if not rooted.is_ok():
            return False

        intent = rooted.unwrap()
        self.repair_attempts_remaining -= 1
        self._repair_intent = (
            f"[REPAIR ITERATION - {intent.summary}; "
            f"{self.repair_attempts_remaining} attempt(s) remaining]\n\n"
            f"{intent.prompt}"
        )
        return True

    def _attempt_lint_repair(self) -> bool:
        """Run lint/format checks and queue a repair intent if issues remain."""
        if self.repair_attempts_remaining <= 0:
            return False
        report = self._lint_repair.check()
        if report.passed:
            return False

        rooted = self._lint_repair.build_repair_prompt(report)
        if not rooted.is_ok():
            return False

        intent = rooted.unwrap()
        self.repair_attempts_remaining -= 1
        self._repair_intent = (
            f"[LINT/FIX ITERATION - {intent['summary']}; "
            f"{self.repair_attempts_remaining} attempt(s) remaining]\n\n"
            f"{intent['prompt']}"
        )
        return True

    def _summarize(self, iterations: list[LoopIteration]) -> str:
        """Produce a final summary of the loop run."""
        if not iterations:
            return "No iterations completed."
        last = iterations[-1]
        passed = sum(1 for it in iterations if it.test_returncode == 0)
        base = (
            f"Completed {len(iterations)} iterations; "
            f"{passed} with passing tests; "
            f"final quality score {last.quality_score}; "
            f"final decision '{last.decision}'."
        )
        ledger_message = self._ledger_breach_message()
        if ledger_message and last.decision == "stop":
            base += f" {ledger_message}"
        return base

    def write_report(self, result: LoopResult, path: Path | str | None = None) -> Path:
        """Serialize the loop result to JSON for later review."""
        target = Path(path) if path else self.project_dir / ".ract" / "loop_report.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        iterations_data = [
            {
                "index": it.index,
                "intent": it.intent,
                "test_returncode": it.test_returncode,
                "test_summary": it.test_summary,
                "test_output": it.test_output,
                "quality_score": it.quality_score,
                "reflection": it.reflection,
                "decision": it.decision,
                "error": it.error,
                "assumptions": it.assumptions,
                "repair_attempt": it.repair_attempt,
                "metrics": it.metrics,
            }
            for it in result.iterations
        ]
        rollup: dict[str, Any] = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "total_latency_ms": 0,
        }
        for it in result.iterations:
            m = it.metrics
            if not m:
                continue
            rollup["total_input_tokens"] += m.get("total_input_tokens", 0)
            rollup["total_output_tokens"] += m.get("total_output_tokens", 0)
            rollup["total_tokens"] += m.get("total_tokens", 0)
            rollup["total_cost"] += m.get("total_cost", 0.0)
            rollup["total_latency_ms"] += m.get("total_latency_ms", 0)
        rollup["total_cost"] = round(rollup["total_cost"], 6)
        data = {
            "final_decision": result.final_decision,
            "summary": result.summary,
            "handshake_milestones": result.handshake_milestones,
            "metrics": rollup,
            "iterations": iterations_data,
        }
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return target


# RACT 0.1.1 - Trust and tooling
