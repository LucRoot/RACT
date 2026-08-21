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
        strict_prompt_digest: bool = False,
        delete_orphaned_files_on_t8: bool = False,
        allow_iter1_delete_orphans: bool = False,
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
        # Cluster 2 finding 4: track prior iteration's plan so a mutation
        # between iterations surfaces as a plan.rewritten event.
        self._prev_iteration_plan: Any | None = None

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

        # ------------------------------------------------------------------
        # v0.5.1 module_04 SP amendments
        # ------------------------------------------------------------------
        # Q4b: opt-in strict mode. When True and suite.prompt_digest is
        # None, T9 PROMPT_DIGEST_MISSING fires. Default preserves
        # v0.5.0 backward-compat; v0.6 flips the default to True.
        self.strict_prompt_digest = strict_prompt_digest
        # Q2: rollback behaviour for orphaned files. Default False
        # (list + emit event) matches OpenRouter reviewer's compromise; True
        # matches Google's stricter fix.
        self.delete_orphaned_files_on_t8 = delete_orphaned_files_on_t8
        # v0.5.1 wiring module_06 (Lens G G-08) closure: iter-1
        # delete-orphans confirmation gate. Default False refuses to
        # wipe files on a drift halt that fires before any iteration
        # has recorded a real workspace snapshot. Operators who WANT
        # aggressive iter-1 cleanup opt in explicitly.
        self.allow_iter1_delete_orphans = allow_iter1_delete_orphans

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

    def _check_prompt_drift(
        self, intent: str, iteration_index: int
    ) -> LoopIteration | None:
        """T8 PROMPT_DRIFT per-iteration hook (v0.5.1 module_04).

        Returns ``None`` when no drift is detected. Returns a synthetic
        :class:`LoopIteration` (with ``decision="regression"`` and a
        drift-diagnostic reflection) when the intent-text hash does
        not match the latest suite's ``prompt_digest``. On drift:

        1. Compute expected + actual digests.
        2. Emit a ``run.completed`` event with the T8 reason payload.
        3. Force the on-disk tree back to
           ``LoopState.last_known_good_workspace`` (or the baseline
           snapshot when no prior iteration has recorded one).
        4. Store the T8 termination cause on the LoopState so any
           downstream reporter surfacing terminations sees it.

        Backward-compat: when ``state.suite.prompt_digest is None``
        (pre-v0.5.1 suite), the check is SKIPPED with a WARN log; the
        loop continues.
        """
        state = self._loop_state
        if state is None:
            return None
        # Publish the current intent text so ``evaluate_termination``'s
        # T8 branch can be reached from property tests using the same
        # state without a controller hook.
        state.current_intent_text = intent

        suite_digest = getattr(state.suite, "prompt_digest", None)
        if suite_digest is None:
            # SP Q4b amendment: opt-in strict mode fires T9
            # PROMPT_DIGEST_MISSING; default preserves v0.5.0 behaviour
            # (skip with WARN).
            if getattr(state, "strict_prompt_digest", False):
                return self._build_missing_digest_iteration(
                    intent, iteration_index, state
                )
            self._log_prompt_drift_skip(state)
            return None

        # Locate the LATEST suite in the chain -- an operator-signed
        # recompile appends new entries, so the check compares against
        # the head, not the initial suite.
        latest_digest = self._latest_suite_prompt_digest(state)
        expected_digest = latest_digest if latest_digest is not None else suite_digest

        from ract.core.workspace_digest import compute_prompt_digest

        actual_digest = bytes(compute_prompt_digest(intent))
        if actual_digest == expected_digest:
            return None

        # DRIFT.
        expected_hex = expected_digest.hex()
        actual_hex = actual_digest.hex()

        # 1. Force rollback to last known-good workspace. Capture the
        # orphan-file list (SP Q2 amendment).
        orphans = self._rollback_to_last_known_good(state)

        # 2. Emit the run.completed event with T8 evidence + orphan
        # list. SP Q2 (external reviewer): the orphan-file surface
        # MUST land in a structured event so operators cannot miss it.
        run_id_str = self._resolve_run_id(state)
        try:
            from ract.trace.sink import emit as _emit_event

            _emit_event(
                "run.completed",
                {
                    "reason": "T8_PROMPT_DRIFT",
                    "expected_prompt_digest": expected_hex,
                    "actual_prompt_digest": actual_hex,
                    "iteration": iteration_index,
                    "run_id": run_id_str,
                    "orphaned_files": list(orphans),
                    "orphaned_files_deleted": bool(
                        self.delete_orphaned_files_on_t8 and orphans
                    ),
                },
            )
        except Exception:  # noqa: BLE001 -- trace failures never break halt
            pass

        # 3. Return a synthetic iteration record so LoopResult carries
        # the diagnostic. The reflection is the operator-visible
        # diagnostic; the run summary quotes the same message. SP Q2
        # amendment: the orphan-file list is inline in the reflection
        # so an operator reading the CLI output sees which files were
        # written under the drifted intent.
        if orphans:
            orphan_line = (
                f" Orphaned files (present but not in snapshot): "
                f"{orphans}. "
                + (
                    "These files were DELETED (delete_orphaned_files_on_t8=True). "
                    if self.delete_orphaned_files_on_t8
                    else "These files were LEFT ALONE; inspect via `git status` "
                    "and delete manually or re-run with "
                    "delete_orphaned_files_on_t8=True. "
                )
            )
        else:
            orphan_line = ""
        reflection = (
            f"T8 PROMPT_DRIFT at iteration {iteration_index}: expected "
            f"prompt_digest {expected_hex}, got {actual_hex}. Workspace "
            f"rolled back to last known-good snapshot.{orphan_line} "
            "To authorise a legitimate intent change, run `ract intent "
            f"recompile {run_id_str}` (requires operator key)."
        )
        return LoopIteration(
            index=iteration_index,
            intent=intent,
            report=None,
            test_returncode=None,
            test_summary="T8 PROMPT_DRIFT",
            test_output=reflection,
            quality_score=0.0,
            reflection=reflection,
            decision="regression",
            error=None,
            assumptions=[],
            metrics={"t8_prompt_drift": True},
            content_snapshot=dict(self._previous_snapshot),
        )

    def _latest_suite_prompt_digest(self, state: LoopState) -> bytes | None:
        """Return the latest suite-chain entry's ``prompt_digest`` or ``None``.

        The chain lives at ``<run_dir>/suite_chain.jsonl``. When the
        chain does not exist yet (no operator recompile has fired),
        return ``None`` so the caller falls back to the frozen
        ``state.suite.prompt_digest``.
        """
        if self.run_dir is None:
            return None
        try:
            from ract.core.suite_chain import SuiteChain

            chain = SuiteChain(self.run_dir)
            return chain.latest_prompt_digest()
        except Exception:  # noqa: BLE001 -- never break the loop on chain read
            return None

    def _resolve_run_id(self, state: LoopState) -> str:
        """Return the run identifier string for a T8 diagnostic.

        v0.5.1 module_06 resolution order:

        1. Ambient run_id (:func:`ract.runtime.get_current_run_id`) --
           set by ``run()`` at entry, so every subsystem the loop
           reaches sees the same value.
        2. ``run_dir/run_id.txt`` marker (persists across invocations).
        3. ``run_dir.name`` basename (pre-module_06 convention).
        """
        from ract.runtime import get_current_run_id

        ambient = get_current_run_id()
        if ambient:
            return ambient
        if self.run_dir is None:
            return "unknown"
        marker = self.run_dir / "run_id.txt"
        if marker.exists():
            try:
                return marker.read_text(encoding="utf-8").strip() or self.run_dir.name
            except OSError:
                pass
        return self.run_dir.name

    def _rollback_to_last_known_good(self, state: LoopState) -> list[str]:
        """Restore the on-disk tree to ``state.last_known_good_workspace``.

        Restores every file recorded in the snapshot. Files that appear
        in the current tree but NOT in the snapshot are ORPHANED --
        they were written under the drifted intent. The controller's
        ``delete_orphaned_files_on_t8`` flag controls what happens to
        them:

        - ``False`` (default): leave the file, return its relative path
          in the returned list. The caller emits a structured
          ``run.completed`` event listing every orphan so the operator
          cannot miss them (SP Q2 external reviewer PARTIAL verdict --
          OpenRouter reviewer's compromise: "emit a structured event listing the
          leftovers so the operator cannot miss them"; Google's stricter
          fix: "delete them" -- the flag lets operators pick).
        - ``True``: delete the orphan file. Aggressive; operators who
          share workspace paths with attackers should set this.

        Failure to restore or delete a specific file is silently
        swallowed -- T8 halt takes precedence over rollback fidelity.

        Returns the list of orphan file relative paths (present in the
        current tree but not in the snapshot). Empty list when snapshot
        is absent or the tree matches the snapshot.
        """
        snapshot = state.last_known_good_workspace
        if snapshot is None:
            return []
        # Restore recorded content.
        for rel_path, content in snapshot.files.items():
            try:
                target = self.project_dir / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            except OSError:
                continue

        # Enumerate orphans: files present in the current tree that
        # are absent from the snapshot. Scan the same way ``_take_snapshot``
        # scans so the orphan set is comparable to the snapshot's file
        # set (Python files only, __pycache__ excluded).
        current = self._take_snapshot()
        recorded = set(snapshot.files.keys())
        orphans = sorted(set(current.keys()) - recorded)

        # Optional delete.
        # v0.5.1 wiring module_06 (Lens G G-08) additional guard: when
        # the recorded snapshot is empty (``files == {}``) the delete
        # path would treat EVERY tracked ``.py`` in ``project_dir`` as
        # an orphan and unlink it. That is safe only when the operator
        # explicitly accepts the aggressive path via
        # ``allow_iter1_delete_orphans=True`` (the flag's name reflects
        # the historical bug it protects against -- iter-1 T8 with the
        # delete-orphans flag on). SP Q6.2 amendment: prior code also
        # gated on ``_rollback_streak == 0`` but that reduced to the
        # same ``not snapshot.files`` check (dead code); the single
        # ``snapshot_is_empty`` signal is the load-bearing one.
        if orphans and self.delete_orphaned_files_on_t8:
            snapshot_is_empty = not snapshot.files
            if snapshot_is_empty and not getattr(
                self, "allow_iter1_delete_orphans", False
            ):
                import logging

                logging.getLogger("ract.loop_controller").warning(
                    "T8 rollback: refusing to delete %d orphaned files on "
                    "iter-1 / empty-snapshot fire (would risk wiping the "
                    "tree). Pass allow_iter1_delete_orphans=True on the "
                    "LoopController to opt in.",
                    len(orphans),
                )
            else:
                for rel_path in orphans:
                    try:
                        (self.project_dir / rel_path).unlink()
                    except OSError:
                        continue

        return orphans

    def _build_missing_digest_iteration(
        self, intent: str, iteration_index: int, state: LoopState
    ) -> LoopIteration:
        """T9 PROMPT_DIGEST_MISSING halt (SP Q4b amendment, strict mode).

        Emits a ``run.completed`` event with reason
        ``"T9_PROMPT_DIGEST_MISSING"`` + returns a synthetic
        regression iteration so the loop halts. Operator must run
        ``ract intent recompile`` to bind a digest before re-running.
        """
        run_id_str = self._resolve_run_id(state)
        try:
            from ract.trace.sink import emit as _emit_event

            _emit_event(
                "run.completed",
                {
                    "reason": "T9_PROMPT_DIGEST_MISSING",
                    "iteration": iteration_index,
                    "run_id": run_id_str,
                },
            )
        except Exception:  # noqa: BLE001
            pass
        reflection = (
            f"T9 PROMPT_DIGEST_MISSING at iteration {iteration_index}: "
            "the AcceptanceSuite has no prompt_digest (pre-v0.5.1 "
            "compile). strict_prompt_digest=True refuses to run without "
            "the binding. Run `ract intent recompile "
            f"{run_id_str} --intent-text ...` to bind a digest, or "
            "start the controller with strict_prompt_digest=False to "
            "revert to permissive-with-warn mode."
        )
        return LoopIteration(
            index=iteration_index,
            intent=intent,
            report=None,
            test_returncode=None,
            test_summary="T9 PROMPT_DIGEST_MISSING",
            test_output=reflection,
            quality_score=0.0,
            reflection=reflection,
            decision="regression",
            error=None,
            assumptions=[],
            metrics={"t9_prompt_digest_missing": True},
            content_snapshot=dict(self._previous_snapshot),
        )

    def _log_prompt_drift_skip(self, state: LoopState) -> None:
        """Log the WARN when T8 is skipped due to a missing prompt_digest.

        Emits ONCE per run to avoid log flooding: subsequent iterations
        do not re-log because ``_prompt_drift_skip_logged`` gates it.
        """
        if getattr(self, "_prompt_drift_skip_logged", False):
            return
        self._prompt_drift_skip_logged = True
        try:
            import logging

            logging.getLogger("ract.loop_controller").warning(
                "T8 PROMPT_DRIFT check skipped: suite.prompt_digest is None "
                "(pre-v0.5.1 AcceptanceSuite). The loop is running without "
                "runtime prompt-drift protection. Recompile the intent under "
                "a v0.5.1 IntentCompiler to enable the check."
            )
        except Exception:  # noqa: BLE001
            pass

    def run(
        self,
        intent: str,
        *,
        done_callback: Callable[[LoopIteration], bool] | None = None,
    ) -> LoopResult:
        """Run the loop and return the final result."""
        # v0.5.1 module_06: bind the ambient run_id for the whole run.
        # Every subsystem that would otherwise fabricate a default
        # (WAL entries, WorkspaceDigestChain edges, SuiteChain
        # initial-entry fallback, Rootknot v4 factory) consults
        # :func:`ract.runtime.get_current_run_id` first. Resolution
        # order for THIS scope: (1) ``run_dir/run_id.txt`` marker when
        # present, (2) ``run_dir.name`` basename, (3) freshly-minted
        # hex id when no run_dir is set. The marker is written after
        # resolution so future subprocess-scoped verifiers can read
        # the same id without an active ambient binding.
        from ract.runtime import bind_run_id

        resolved_run_id = self._resolve_or_mint_run_id()
        with bind_run_id(resolved_run_id):
            return self._run_bound(intent, done_callback=done_callback)

    def _resolve_or_mint_run_id(self) -> str:
        """Resolve the run_id for this run, minting one if necessary.

        Called once at ``run()`` entry. Resolution order:

        1. ``run_dir/run_id.txt`` marker (persists across invocations
           targeting the same run_dir — matches
           :meth:`_resolve_run_id`).
        2. ``run_dir.name`` when it looks like a fresh identifier
           (kept for backward-compat with pre-module_06 controllers
           that never wrote the marker).
        3. A freshly-minted 32-hex id via
           :func:`ract.core.workspace_digest.run_id_hex` when neither
           of the above applies.

        Whenever a fresh id is minted the marker is also written so
        the next invocation targeting the same run_dir picks up the
        same id (compaction preserves the identifier).

        SP Q4 amendment (external reviewer DEFECT verdict): the
        check-then-mint sequence is atomic under a cross-platform
        exclusive lock on a ``run_id.txt.lock`` sidecar. Without the
        lock, two RACT processes racing on the same fresh run_dir
        could each observe marker-absent, mint different ids, and
        write both into the ledger -- turning a single run_dir into
        a mosaic of two run_ids. The lock closes the window by
        serialising the check + write. Marker writes remain
        best-effort -- a failing write does not break the loop.
        """
        import os as _os

        from ract.core.workspace_digest import run_id_hex

        if self.run_dir is not None:
            marker = self.run_dir / "run_id.txt"
            # First-chance read outside the lock avoids contention on
            # the common resolve-existing path.
            if marker.exists():
                try:
                    existing = marker.read_text(encoding="utf-8").strip()
                except OSError:
                    existing = ""
                if existing:
                    return existing
            try:
                self.run_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return run_id_hex()
            lock_path = self.run_dir / "run_id.txt.lock"
            base = self.run_dir.name.strip()
            candidate = base if base else run_id_hex()
            try:
                fd = _os.open(
                    lock_path,
                    _os.O_WRONLY | _os.O_CREAT,
                    0o644,
                )
            except OSError:
                try:
                    marker.write_text(candidate, encoding="utf-8")
                except OSError:
                    pass
                return candidate
            try:
                self._acquire_marker_lock(fd)
                try:
                    # Re-check marker under lock (double-checked pattern).
                    if marker.exists():
                        try:
                            existing = marker.read_text(encoding="utf-8").strip()
                        except OSError:
                            existing = ""
                        if existing:
                            return existing
                    try:
                        marker.write_text(candidate, encoding="utf-8")
                    except OSError:
                        pass
                    return candidate
                finally:
                    self._release_marker_lock(fd)
            finally:
                try:
                    _os.close(fd)
                except OSError:
                    pass
        return run_id_hex()

    @staticmethod
    def _acquire_marker_lock(fd: int) -> None:
        """Cross-platform exclusive lock on the marker lock sidecar."""
        import os as _os
        import sys as _sys
        import time as _time

        if _sys.platform == "win32":
            import msvcrt  # type: ignore[import-not-found]

            _os.lseek(fd, 0, _os.SEEK_SET)
            for _attempt in range(3):
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError:
                    _time.sleep(0.01)
        else:
            import fcntl  # type: ignore[import-not-found,unused-ignore,attr-defined,no-redef]

            for _attempt in range(3):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
                    return
                except OSError:
                    _time.sleep(0.01)

    @staticmethod
    def _release_marker_lock(fd: int) -> None:
        """Release the exclusive lock acquired via
        :meth:`_acquire_marker_lock`.
        """
        import os as _os
        import sys as _sys

        if _sys.platform == "win32":
            import msvcrt  # type: ignore[import-not-found]

            _os.lseek(fd, 0, _os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl  # type: ignore[import-not-found,unused-ignore,attr-defined,no-redef]

            try:
                fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
            except OSError:
                pass

    def _run_bound(
        self,
        intent: str,
        *,
        done_callback: Callable[[LoopIteration], bool] | None = None,
    ) -> LoopResult:
        """Body of :meth:`run` executed under the bound ambient run_id."""
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
                strict_prompt_digest=self.strict_prompt_digest,
            )
            # v0.5.1 wiring module_06 (Lens G G-03) closure: re-seed
            # ``last_known_good_workspace`` on the freshly-built
            # LoopState from the resume snapshot, so a T8 halt in the
            # FIRST iteration after resume still has a rollback target.
            resume_last_known = getattr(self, "_resume_last_known_good", None)
            if resume_last_known is not None and self._loop_state is not None:
                self._loop_state.last_known_good_workspace = resume_last_known
                self._resume_last_known_good = None
            user_done = done_callback
            done_callback = self._make_suite_done_callback(user_done)

        # v0.5.1 wiring module_06 (Lens G G-03, G-04, G-05) closure:
        # loop-resume path. When a prior invocation on this run_dir
        # persisted iteration state via ``on_pause`` (or per-iter
        # auto-persist below), start counting AT the persisted
        # iteration + 1 rather than resetting to 1. Fresh runs (no
        # sidecar) hit ``start_index = 1``. The stashed counters live
        # in ``self._resume_snapshot`` -- populated by
        # :meth:`on_resume` or the public :meth:`resume` entry point.
        resume_snapshot: dict[str, Any] | None = getattr(
            self, "_resume_snapshot", None
        )
        if resume_snapshot is not None:
            iterations = list(resume_snapshot.get("iterations", []))
            previous_score = resume_snapshot.get("previous_score")
            stagnation_count = int(resume_snapshot.get("stagnation_count", 0))
            start_index = int(resume_snapshot.get("iterations_count", 0)) + 1
            # Drop the snapshot so a subsequent ``run()`` on the same
            # controller does not re-consume it.
            self._resume_snapshot = None
        else:
            iterations = []
            previous_score = None
            stagnation_count = 0
            start_index = 1

        for index in range(start_index, self.max_iterations + 1):
            current_milestone = self._current_milestone()
            if current_milestone is None and self.backlog is not None:
                return LoopResult(
                    iterations=iterations,
                    final_decision="done",
                    summary="All milestones completed.",
                    handshake_milestones=list(self.handshake_milestones),
                )

            # v0.5.1 wiring module_06 (Lens G G-08) closure: capture
            # snapshot state BEFORE the T8 drift check. The prior
            # ordering (drift-check first, snapshot-init second) meant
            # that on iter-1 a T8 halt would run
            # ``_rollback_to_last_known_good`` with an empty
            # ``last_known_good_workspace`` (or a snapshot whose
            # ``files={}`` from a controller pre-seed), so
            # ``_take_snapshot() - set()`` marked EVERY tracked file in
            # ``project_dir`` as an orphan. With
            # ``delete_orphaned_files_on_t8=True`` and a partially
            # populated snapshot, iter-1 T8 could wipe the tree. This
            # block now runs first so ``last_known_good_workspace`` is
            # populated from the tree-at-entry BEFORE any drift check
            # reads it.
            if not self._snapshot_initialized:
                self._baseline_snapshot = self._take_snapshot()
                self._previous_snapshot = dict(self._baseline_snapshot)
                self._snapshot_initialized = True

            # v0.5.1 module_04: record the last-known-good workspace on
            # the LoopState BEFORE the iteration writes anything. On a
            # T8 halt in a later iteration, the controller rolls the
            # tree back to this snapshot's file contents.
            if self._loop_state is not None:
                self._loop_state.last_known_good_workspace = WorkspaceSnapshot(
                    files=dict(self._previous_snapshot),
                    timestamp=float(index),
                    metadata=dict(
                        self._loop_state.last_known_good_workspace.metadata
                        if self._loop_state.last_known_good_workspace is not None
                        else {}
                    ),
                )

            # v0.5.1 module_04: T8 PROMPT_DRIFT check at the START of
            # each iteration, AFTER snapshot init so
            # ``_rollback_to_last_known_good`` has a real target if a
            # drift halt fires on iter-1 (Lens G G-08 fix). Compare the
            # raw operator ``intent`` (the bytes
            # ``IntentCompiler.compile`` hashed into
            # ``suite.prompt_digest``) against the LATEST suite in the
            # chain (post-operator-recompile awareness). Mismatch =>
            # halt with T8 + rollback + surfaced diagnostic. See
            # ``docs/ADRs/ADR-0040-t8-prompt-drift-termination-cause.md``.
            drift_result = self._check_prompt_drift(intent, index)
            if drift_result is not None:
                iterations.append(drift_result)
                return LoopResult(
                    iterations=iterations,
                    final_decision="regression",
                    summary=(
                        "T8 PROMPT_DRIFT: current intent hash does not match "
                        "suite.prompt_digest. Loop halted; workspace rolled "
                        "back to last known-good snapshot. Use `ract intent "
                        "recompile <run_id>` (operator key required) to "
                        "authorise intent evolution."
                    ),
                    handshake_milestones=list(self.handshake_milestones),
                )

            iteration_intent = self._augment_intent(
                intent, iterations, current_milestone
            )

            result = self._run_with_timeout(iteration_intent)

            report = result.unwrap() if result.is_ok() else None
            # Cluster 2 finding 4: emit plan.rewritten when the new
            # iteration's plan differs from the previous iteration's
            # plan. First iteration has no prior plan, so nothing to
            # diff against.
            self._maybe_emit_plan_rewritten(report)
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

            # v0.5.1 wiring module_06 (Lens G G-04) closure: persist
            # iteration state at each boundary so a compaction /
            # restart can resume from the current iteration count
            # rather than restarting at 1. Best-effort: a failing
            # write does not break the loop -- the resume path
            # tolerates a missing sidecar by starting fresh.
            self._persist_iteration_state(
                iterations=iterations,
                previous_score=previous_score,
                stagnation_count=stagnation_count,
            )

        return LoopResult(
            iterations=iterations,
            final_decision="stop",
            summary=f"Reached max iterations ({self.max_iterations}).",
            handshake_milestones=list(self.handshake_milestones),
        )

    # ------------------------------------------------------------------
    # v0.5.1 wiring module_06 (Lens G G-03, G-04, G-05) closure --
    # loop-resume path
    # ------------------------------------------------------------------

    _LOOP_STATE_SIDECAR_NAME = "loop_state.json"

    def _loop_state_sidecar_path(self) -> Path | None:
        """Return the sidecar path for persisted loop-resume state.

        Lives at ``<run_dir>/loop_state.json`` when ``run_dir`` is set.
        Returns ``None`` for controllers without a ``run_dir`` (which
        cannot participate in the resume path -- there is nowhere to
        persist).
        """
        if self.run_dir is None:
            return None
        return self.run_dir / self._LOOP_STATE_SIDECAR_NAME

    def _serialize_iteration(self, iteration: LoopIteration) -> dict[str, Any]:
        """Serialize a :class:`LoopIteration` to a JCS-safe dict.

        The report / plan objects are dropped -- they hold live
        provider objects that cannot round-trip. What survives is the
        counter surface the resume path needs (index, decision,
        quality_score, test_returncode, error, metrics, content).
        """
        return {
            "index": iteration.index,
            "intent": iteration.intent,
            "test_returncode": iteration.test_returncode,
            "test_summary": iteration.test_summary,
            "test_output": iteration.test_output,
            "quality_score": iteration.quality_score,
            "reflection": iteration.reflection,
            "decision": iteration.decision,
            "error": iteration.error,
            "assumptions": list(iteration.assumptions),
            "repair_attempt": iteration.repair_attempt,
            "metrics": dict(iteration.metrics),
            "content_snapshot": dict(iteration.content_snapshot),
        }

    def _deserialize_iteration(self, payload: dict[str, Any]) -> LoopIteration:
        """Reconstruct a :class:`LoopIteration` from a persisted dict.

        ``report`` is ``None`` -- the live executor object cannot round
        trip. The resume path only needs the counters + reflection for
        subsequent iterations' heuristics; the report was consumed
        immediately in the original iteration.
        """
        return LoopIteration(
            index=int(payload["index"]),
            intent=str(payload["intent"]),
            report=None,
            test_returncode=payload.get("test_returncode"),
            test_summary=str(payload.get("test_summary", "")),
            test_output=str(payload.get("test_output", "")),
            quality_score=float(payload.get("quality_score", 0.0)),
            reflection=str(payload.get("reflection", "")),
            decision=str(payload.get("decision", "continue")),
            error=payload.get("error"),
            assumptions=list(payload.get("assumptions", [])),
            repair_attempt=bool(payload.get("repair_attempt", False)),
            metrics=dict(payload.get("metrics", {})),
            content_snapshot=dict(payload.get("content_snapshot", {})),
        )

    def _current_persist_payload(
        self,
        *,
        iterations: list[LoopIteration],
        previous_score: float | None,
        stagnation_count: int,
    ) -> dict[str, Any]:
        """Return the JCS-safe snapshot of resumable loop state.

        Fields captured (per Lens G G-04 remediation):
        ``iterations``, ``previous_score``, ``stagnation_count``,
        ``_rollback_streak``, ``_prev_iteration_plan`` (dropped: live
        Plan object), ``_completed_families``, ``repair_attempts_remaining``,
        ``_repair_intent``, ``last_known_good_workspace``.
        """
        last_known: dict[str, Any] | None = None
        state = self._loop_state
        if state is not None and state.last_known_good_workspace is not None:
            snap = state.last_known_good_workspace
            last_known = {
                "files": dict(snap.files),
                "timestamp": float(snap.timestamp),
                "metadata": dict(snap.metadata),
            }
        return {
            "iterations": [self._serialize_iteration(it) for it in iterations],
            "iterations_count": len(iterations),
            "previous_score": previous_score,
            "stagnation_count": int(stagnation_count),
            "rollback_streak": int(self._rollback_streak),
            "completed_families": list(self._completed_families),
            "repair_attempts_remaining": int(self.repair_attempts_remaining),
            "repair_intent": self._repair_intent,
            "last_known_good_workspace": last_known,
            "handshake_milestones": list(self.handshake_milestones),
        }

    def _persist_iteration_state(
        self,
        *,
        iterations: list[LoopIteration],
        previous_score: float | None,
        stagnation_count: int,
    ) -> None:
        """Best-effort JCS write of loop state to the sidecar.

        Called at each iteration boundary AND from :meth:`on_pause`.
        Failure to write does not break the loop -- a missing sidecar
        on resume just starts fresh.
        """
        sidecar = self._loop_state_sidecar_path()
        if sidecar is None:
            return
        payload = self._current_persist_payload(
            iterations=iterations,
            previous_score=previous_score,
            stagnation_count=stagnation_count,
        )
        # The sidecar is a self-describing state file, NOT a hash
        # input, so canonical order is convenient (grep-friendly) but
        # not load-bearing. Prefer JCS to keep parity with the rest
        # of the codebase; fall back to plain ``json.dumps`` when the
        # canonical module cannot be imported (deep-dependency edge
        # cases). The fallback deliberately omits ``sort_keys=True``
        # so the architecture grep-gate for
        # ``ract.canonical.dumps_jcs`` migration stays honest.
        try:
            from ract.canonical import dumps_jcs
        except Exception:  # noqa: BLE001 -- deep dependency, tolerate absence
            import json as _json

            body = _json.dumps(payload, ensure_ascii=False)
        else:
            raw = dumps_jcs(payload)
            body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        try:
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(body, encoding="utf-8")
        except OSError:
            # Best-effort: log at INFO, do not raise.
            import logging

            logging.getLogger("ract.loop_controller").info(
                "loop_state.json persist failed for run_dir %s; resume "
                "will start fresh.",
                self.run_dir,
            )

    def on_pause(
        self,
        *,
        iterations: list[LoopIteration] | None = None,
        previous_score: float | None = None,
        stagnation_count: int = 0,
    ) -> None:
        """Persist loop state BEFORE an external event (e.g., compaction).

        Callers that know a compaction / checkpoint is imminent invoke
        this to flush the current counters to the sidecar. Passing the
        iteration list explicitly is required from external orchestrators;
        the loop's own per-iter auto-persist writes the same content
        without arguments needed. See Lens G G-05: promotes compaction
        to a first-class event with an explicit persist protocol.
        """
        self._persist_iteration_state(
            iterations=iterations or [],
            previous_score=previous_score,
            stagnation_count=stagnation_count,
        )

    def on_resume(self, state_path: Path | str | None = None) -> bool:
        """Load persisted loop state from the sidecar and stage it for
        the next :meth:`run` call.

        Returns True when a valid sidecar was consumed; False when the
        sidecar is missing / unreadable / semantically invalid. When
        True, the next call to :meth:`run` (or :meth:`resume`) skips
        the counter reset and starts the ``for index`` loop at the
        persisted ``iterations_count + 1``. Also restores
        ``_rollback_streak``, ``_completed_families``,
        ``repair_attempts_remaining``, ``_repair_intent``, and
        ``last_known_good_workspace`` on the controller / LoopState.
        """
        path: Path | None
        if state_path is not None:
            path = Path(state_path)
        else:
            path = self._loop_state_sidecar_path()
        if path is None or not path.exists():
            return False
        try:
            body = path.read_text(encoding="utf-8")
            payload = json.loads(body)
        except (OSError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False
        # Rehydrate the controller-level counters. The iteration list
        # is rehydrated as :class:`LoopIteration` instances so
        # ``_run_bound``'s ``iterations`` variable can carry a
        # coherent history for report-writers.
        try:
            iterations = [
                self._deserialize_iteration(entry)
                for entry in payload.get("iterations", [])
            ]
        except (KeyError, TypeError, ValueError):
            return False
        self._resume_snapshot = {
            "iterations": iterations,
            "iterations_count": int(payload.get("iterations_count", len(iterations))),
            "previous_score": payload.get("previous_score"),
            "stagnation_count": int(payload.get("stagnation_count", 0)),
        }
        self._rollback_streak = int(payload.get("rollback_streak", 0))
        self._completed_families = list(payload.get("completed_families", []))
        self.repair_attempts_remaining = int(
            payload.get("repair_attempts_remaining", 0)
        )
        self._repair_intent = payload.get("repair_intent")
        self.handshake_milestones = list(payload.get("handshake_milestones", []))
        # Rehydrate the last-known-good snapshot on the loop state
        # (needed for T8 rollback to survive resume -- Lens G G-03).
        last_known = payload.get("last_known_good_workspace")
        if last_known is not None:
            snap = WorkspaceSnapshot(
                files=dict(last_known.get("files", {})),
                timestamp=float(last_known.get("timestamp", 0.0)),
                metadata=dict(last_known.get("metadata", {})),
            )
            # Stash on the controller so ``_run_bound`` (which may
            # rebuild ``_loop_state`` from the suite) can seed the
            # loop state's ``last_known_good_workspace`` field after
            # ``build_loop_state`` returns.
            self._resume_last_known_good = snap
        return True

    def resume(
        self,
        intent: str,
        *,
        state_path: Path | str | None = None,
        done_callback: Callable[[LoopIteration], bool] | None = None,
    ) -> LoopResult:
        """Public entry point for restart-with-resume.

        Reads the persisted state via :meth:`on_resume` and enters
        :meth:`run` so the iteration counter continues from the persisted
        count instead of resetting to 1. If no sidecar exists, behaves
        exactly like :meth:`run` (fresh start).
        """
        self.on_resume(state_path=state_path)
        return self.run(intent, done_callback=done_callback)

    def _maybe_emit_plan_rewritten(self, report: Any) -> None:
        """Emit ``plan.rewritten`` when the report carries a mutated plan.

        Cluster 2 finding 4. Diffs the incoming iteration's plan
        against the previous iteration's plan; an empty diff (identical
        step content, position-preserved) emits nothing. When a diff is
        present, publishes to the module-level trace sink so any run
        that registered a writer captures the mutation. First iteration
        has no prior plan, so the emit is skipped there.
        """
        plan_candidate: Any | None = None
        if isinstance(report, ExecutionReport):
            plan_candidate = report.plan
        elif isinstance(report, Plan):
            plan_candidate = report
        if plan_candidate is None:
            return

        prev = self._prev_iteration_plan
        self._prev_iteration_plan = plan_candidate
        if prev is None:
            return

        try:
            from ract.core.plan import diff_manager_plans
            from ract.trace.sink import emit as _emit_event

            diff = diff_manager_plans(prev, plan_candidate)
            if diff.is_empty():
                return
            _emit_event("plan.rewritten", diff.to_payload())
        except Exception:  # noqa: BLE001 — trace failures never break the loop
            pass

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
            # v0.5.1 wiring module_07 (Lens E AL-E-01): fire sycophancy_v2
            # per-iteration against the primary's (intent, response) pair.
            # Emits ``whisperer.contract_violation`` when the response is
            # null-op or sub-floor commitment. Never blocks the loop by
            # itself — the emission is the signal a downstream verifier
            # reads.
            self._run_sycophancy_v2_check(iteration)
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
            # v0.5.1 wiring module_07 (Lens E AL-E-02): polyglot G5/G6
            # per-file dispatcher. Fires unconditionally at T1 completion
            # so a .ts / .rs / .go patch is analyzed instead of silently
            # skipped. Backward-compat: an all-Python workspace routes
            # through the Python-AST backend via the same dispatcher, so
            # legacy behavior for pure-Python callers is preserved.
            polyglot_block = self._run_polyglot_g5_g6(iteration)
            if polyglot_block:
                self._repair_intent = polyglot_block
                return False
            # v0.5.1 wiring module_07 (Lens E AL-E-03): canonical G1/G7/G8
            # dispatchers with laziness.skipped emission. Runs alongside
            # the completion_gates path so the trace channel carries a
            # skip event when the caller did not provide the gate
            # inputs. Does NOT block completion by itself — the
            # completion_gates path above is the authoritative one for
            # G7/G8's block decision; the enforce_gN wrappers here are
            # the AL-1 evidence-attestation surface.
            self._run_canonical_g1_g7_g8(iteration)
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

    # ------------------------------------------------------------------
    # v0.5.1 wiring module_07 — anti-lazy dispatch wire-in
    # ------------------------------------------------------------------

    def _extract_response_text(self, iteration: LoopIteration) -> str:
        """Return the primary's response text for the iteration, or ``""``.

        The sycophancy_v2 classifier reads (request, response) pairs.
        Substrate v0.4's :class:`ExecutionReport` carries the response
        text as :attr:`StepResult.content`; aggregate across steps so
        a multi-step iteration surfaces the full primary output. When
        the report is a plain :class:`Plan` (planning-only iteration)
        or is missing, return the empty string — the classifier
        short-circuits on empty text so it is a safe no-op.
        """
        report = getattr(iteration, "report", None)
        step_results = getattr(report, "step_results", None)
        if not step_results:
            return ""
        parts: list[str] = []
        for sr in step_results:
            content = getattr(sr, "content", None)
            if isinstance(content, str) and content:
                parts.append(content)
        return "\n\n".join(parts)

    def _run_sycophancy_v2_check(self, iteration: LoopIteration) -> None:
        """Fire sycophancy_v2 per iteration; emit on sycophantic verdict.

        Never raises; never blocks the loop. The
        ``whisperer.contract_violation`` emit is best-effort — the
        classifier's own :meth:`SycophancyClassification.emit_event`
        guards the trace-sink import.

        v0.5.1 wiring module_07 (Lens E AL-E-01) closure. Replaces the
        legacy multi-turn sycophancy scanner (which had zero live
        callers) with the two-signal per-request/response classifier
        as the loop's per-iteration sycophancy signal.
        """
        request = iteration.intent or ""
        response = self._extract_response_text(iteration)
        if not request or not response:
            return
        try:
            from ract.antilazy.sycophancy_v2 import (  # noqa: PLC0415
                classify as classify_sycophancy_v2,
            )

            classification = classify_sycophancy_v2(request, response)
            classification.emit_event()
        except Exception:  # noqa: BLE001 — never break the loop on sycophancy check error
            return

    def _collect_changed_polyglot_files(
        self, iteration: LoopIteration
    ) -> list[Path]:
        """Return the polyglot-scannable paths touched since baseline.

        Walks ``project_dir`` for the polyglot-supported extensions
        (.py, .ts, .tsx, .js, .jsx, .rs, .go, .rb — see
        :data:`ract.antilazy.pre_commit._POLYGLOT_SUPPORTED_EXTS`).
        A file whose contents differ from the baseline snapshot is a
        changed file; new files (present in the tree but not in the
        baseline) count as changed. Deleted files (present in the
        baseline but not on disk) are dropped because the polyglot
        scanners walk actual files.
        """
        from ract.antilazy.pre_commit import (  # noqa: PLC0415
            _POLYGLOT_SUPPORTED_EXTS,
        )

        if not self.project_dir.is_dir():
            return []
        changed: list[Path] = []
        baseline = self._baseline_snapshot or {}
        for path in self.project_dir.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            if path.suffix.lower() not in _POLYGLOT_SUPPORTED_EXTS:
                continue
            try:
                rel = str(path.relative_to(self.project_dir))
            except ValueError:
                continue
            try:
                current_text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            baseline_text = baseline.get(rel)
            if baseline_text is None or baseline_text != current_text:
                changed.append(path)
        return changed

    def _run_polyglot_g5_g6(self, iteration: LoopIteration) -> str:
        """Run the polyglot G5 + G6 dispatcher on this iteration's changes.

        Returns a resume prompt string (non-empty when either gate
        blocks) or ``""`` when both pass. On empty changed-file set
        (iteration 1 pre-write, or a planning-only iteration) both
        gates return ``passed=True`` and this method returns ``""``.

        v0.5.1 wiring module_07 (Lens E AL-E-02) closure. Replaces the
        prior Python-AST-only path so a .ts / .rs / .go patch is
        analyzed by the tree-sitter backend and a real dead-code /
        copy-paste verdict lands on the trace channel with language
        attribution.
        """
        try:
            changed = self._collect_changed_polyglot_files(iteration)
            if not changed:
                return ""
            from ract.antilazy.pre_commit import (  # noqa: PLC0415
                dispatch_polyglot_g5_g6,
            )

            dead_code, copy_paste = dispatch_polyglot_g5_g6(changed)
            # AL-1 invariant guard: refuse an outcome carrying an
            # empty signature. Defense-in-depth against a
            # future-refactored enforce_gN that forgets to populate
            # the field.
            self._require_al1_signature(dead_code, gate_id="G5-polyglot")
            self._require_al1_signature(copy_paste, gate_id="G6-polyglot")
            if dead_code.passed and copy_paste.passed:
                return ""
            parts: list[str] = []
            if not dead_code.passed:
                parts.append(
                    "[G5 POLYGLOT] dead-code candidates surfaced in the "
                    "changed files across one or more languages. Remove "
                    "the dead code or wire the callers before completing."
                )
            if not copy_paste.passed:
                parts.append(
                    "[G6 POLYGLOT] copy-pasted test bodies surfaced in "
                    "the changed files. Replace with a shared helper or "
                    "distinguish the assertions."
                )
            return "\n\n".join(parts)
        except Exception:  # noqa: BLE001 — never break the loop on gate error
            return ""

    def _run_canonical_g1_g7_g8(self, iteration: LoopIteration) -> None:
        """Fire the canonical G1/G7/G8 dispatchers for AL-1 evidence.

        Uses :func:`ract.antilazy.pre_commit.enforce_g1` / ``_g7`` /
        ``_g8``. Each call produces an ``*GateOutcome`` carrying a
        non-empty ``rootknot_signature`` (AL-1). ``laziness.skipped``
        emits when a caller did not provide the gate inputs. Does not
        block completion — the block decision remains with
        :func:`_run_completion_gates` for G7/G8 and with the substrate
        ``check_t1`` dual-suite branch for G1; this method's job is
        to surface an AL-1 attestation + a trace-channel skip event
        for the gates that ran (or intentionally did not) this
        iteration.
        """
        try:
            from ract.antilazy.pre_commit import (  # noqa: PLC0415
                enforce_g1,
                enforce_g7,
                enforce_g8,
            )

            state = self._loop_state
            dual_suite = None
            snapshot = None
            visible_suite = None
            if state is not None:
                suite = state.suite
                if hasattr(suite, "visible") and hasattr(suite, "held_out"):
                    dual_suite = suite
                    visible_suite = suite.visible
                else:
                    visible_suite = suite
                snapshot = state.workspace
            g1_outcome = enforce_g1(dual_suite, snapshot)
            self._require_al1_signature(g1_outcome, gate_id="G1")
            final_diff = self._final_diff_for_gates(iteration)
            g7_outcome = enforce_g7(
                intent=iteration.intent,
                final_diff=final_diff,
                visible_suite=visible_suite,
                companion_bundle=self.companion,
                pre_change_workspace=self._pre_change_workspace_for_gates(),
                post_change_workspace=self._post_change_workspace_for_gates(),
            )
            self._require_al1_signature(g7_outcome, gate_id="G7")
            g8_outcome = enforce_g8(
                final_diff=final_diff,
                effort_estimate=self.effort_estimate,
            )
            self._require_al1_signature(g8_outcome, gate_id="G8")
        except ValueError:
            # AL-1 invariant violation is loud — re-raise so the loop
            # halts. Any callsite constructing a GateOutcome by hand
            # without a signature is a substrate bug, not a loop bug.
            raise
        except Exception:  # noqa: BLE001 — never break the loop on gate error
            return

    def _require_al1_signature(self, outcome: Any, *, gate_id: str) -> None:
        """Reject a gate outcome carrying an empty AL-1 signature.

        Delegates to
        :func:`ract.antilazy.pre_commit._require_gate_signature` — the
        loop-controller call site keeps the invariant tight so a
        future refactor that forgets to populate the field on a new
        enforce_gN cannot slip through unnoticed.
        """
        signature = getattr(outcome, "rootknot_signature", None)
        from ract.antilazy.pre_commit import (  # noqa: PLC0415
            _require_gate_signature,
        )

        _require_gate_signature(signature or "", gate_id=gate_id)

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
        # v0.5.1 wiring module_06 (Lens G G-02) closure: use the
        # controller's canonical ambient -> marker -> basename resolver
        # so the iso-perturb telemetry is stamped with the same run_id
        # every other subsystem in this run sees. The prior hand-rolled
        # ``self.run_dir.name`` bypassed the ambient/marker precedence.
        run_id = self._resolve_run_id(state) if state is not None else None
        return run_iso_perturb_gate(
            intent=iteration.intent,
            workspace=workspace,
            original_solution=original_solution,
            bundle=self.iso_perturb,
            run_id=run_id,
        )

    def _iso_perturb_original_solution(self, iteration: LoopIteration) -> str | None:
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

        v0.5.1 wiring module_06 (Lens G G-01) closure: the worker call
        is wrapped in :func:`ract.runtime.run_with_ambient` so the
        ambient run_id bound by :meth:`run` at loop entry propagates
        into the :class:`concurrent.futures.ThreadPoolExecutor` worker.
        A bare :meth:`ThreadPoolExecutor.submit` does NOT inherit the
        caller's :class:`contextvars.ContextVar` values -- this is the
        exact hole ``run_with_ambient`` was written to close.
        """
        from ract.runtime import run_with_ambient

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                run_with_ambient(
                    run_ract,
                    self.config_path,
                    intent,
                    yolo=True,
                    allow_load_bearing_override=self.allow_load_bearing_override,
                    allow_novelty_overrun=self.allow_novelty_overrun,
                )
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
