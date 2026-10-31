"""Executor → SubstrateLoop adapter shim (SUBSTRATE §3).

module_08, Path (d) of the ``SubstrateLoop-as-CLI-default`` migration.

The v0.3 executor writes artifacts directly into ``project_dir``. v0.4
routes those writes through worktree-per-step transactions (SUBSTRATE
§3: Transactional Execution). Rather than refactor
``Executor.execute`` — whose 89 call sites in ``tests/test_executor.py``
would need lockstep updates — this adapter wraps the executor at the
plan boundary:

- One ``StepTransaction`` per ``PlannedStep`` (via
  ``ract.core.transaction.open_transaction``).
- A ``StepRunner`` closure calls the existing ``Executor.execute``
  with a single-step ``Plan`` while ``executor.project_dir`` and
  ``executor.diff_applier.project_dir`` are temporarily rebound to
  the worktree path. On exit, both attributes are restored — even if
  the closure raises. ``_write_artifact`` / ``_apply_diff_if_needed`` /
  ``_check_load_bearing`` / ``_record_provenance`` therefore land
  inside the worktree without any Executor internals changing.
- ``SubstrateLoop.run_step`` drives the transaction; its ``_finalize``
  step evaluates post-conditions (module_01's predicates), commits the
  worktree branch on success, and rolls back on any post-condition
  failure or unresolved handshake. The invariant enforcement lives
  there, unchanged by this shim.

The returned ``Rooted[ExecutionReport]`` aggregates the per-step
executor reports so callers see the same value shape they would have
received from ``Executor.execute(intent, plan, ...)`` on a plan of
identical steps.

See ``docs/RACT_v0.4.0_SUBSTRATE_SPEC.md`` §3 for the transactional
model, and ``docs/ADRs/ADR-0011-worktree-per-step.md`` for the
per-step branch discipline this shim depends on.
"""

from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

from ract import plan_gate, run_checkpoint, turn_context, undo_backup
from ract.core.loop import WorkspaceSnapshot
from ract.core.predicate import PredicateResult
from ract.core.transaction import ResourceBudget, TransactionOutcome
from ract.executor.loop import SubstrateLoop, SubstrateStepSpec
from ract.executor.steps import ExecutionReport, Executor
from ract.executor.worktree import (
    apply_commit_to_working_tree,
    WorktreeManager,
    take_snapshot,
    ensure_git_repo,
    WorktreeError,
)
from ract.manager import Plan, Step
from ract.rooted import Rooted

if TYPE_CHECKING:  # pragma: no cover
    from ract.harness import Harness


# Every executor-held helper that captured project_dir at construction
# time must be rebound in lockstep with executor.project_dir; otherwise
# the helper's reads land in the parent tree while the executor's writes
# land in the worktree, producing a silent invariant break. Retroactive
# audit D6 (2026-07-27) surfaced LoadBearingGuard as an uncovered case;
# this list is the enumeration all helpers that hold a project-anchored
# path attribute the executor consults during a step.
_HELPER_ATTRS: tuple[str, ...] = (
    "diff_applier",
    "load_bearing_guard",
    "duplication_guard",
    "novelty_budget",
    "compression_novelty_detector",
)


@contextmanager
def _rebind_project_dir(executor: Executor, new_dir: Path) -> Iterator[None]:
    """Temporarily point ``executor.project_dir`` and every executor-held
    helper's ``project_dir`` at ``new_dir``.

    Restores every rebound attribute on exit, even if the wrapped code
    raises. This is the entire mechanism by which existing per-step
    Executor writes and reads land inside the worktree without any
    change to ``Executor.execute``'s internals.

    Helpers covered (each holds a project-anchored path attribute the
    executor consults during a step):

    - ``diff_applier`` (unified-diff apply targets)
    - ``load_bearing_guard`` (scans annotated files in project_dir)
    - ``duplication_guard`` (walks project_dir for symbol matches)
    - ``novelty_budget`` (persists .ract/novelty_budget.json under project_dir)
    - ``compression_novelty_detector`` (walks project_dir for corpus)

    A helper that does not carry a ``project_dir`` attribute is skipped;
    if a future helper is added, add its attribute name to
    ``_HELPER_ATTRS`` above so the shim covers it.
    """
    new_path = Path(new_dir)
    original_project_dir = executor.project_dir
    originals: list[tuple[Any, Path]] = []
    for attr in _HELPER_ATTRS:
        helper = getattr(executor, attr, None)
        if helper is None:
            continue
        original = getattr(helper, "project_dir", None)
        if original is None:
            continue
        originals.append((helper, original))
    original_in_worktree = executor.in_step_worktree
    try:
        executor.project_dir = new_path
        # The step agent loop writes only here (B-110 D5).
        executor.in_step_worktree = True
        for helper, _original in originals:
            helper.project_dir = new_path
        yield
    finally:
        executor.project_dir = original_project_dir
        executor.in_step_worktree = original_in_worktree
        for helper, original in originals:
            helper.project_dir = original


def _path_tier(repo: Path, path: str) -> str:
    """``T2`` for a control or executable-configuration file, else ``T1``."""
    from ract.tools import ToolRefused
    from ract.tools.write import path_tier

    try:
        return path_tier(repo, path).value
    except ToolRefused:
        return "T2"  # a protected path is never below tier 2 on screen


def _review_proposed(
    harness: Any, reviewer: Any, record: Any, index: int
) -> Rooted[str]:
    """Proposed -> reviewed (ADR-0047 D6): the commit to apply, as the operator kept it.

    LR:: The step's changes are in its commit, not yet in the operator's
    files. Each changed file is shown as ``diff.proposed`` and the reviewer
    answers per hunk; the kept contents become a commit on top of the step's
    (``reviewed_commit``), and the usual apply, with its digest check, takes
    that one. A rejected hunk never reaches the live tree. A review that ends
    without an answer applies nothing and names the branch the proposal is on.
    """
    from ract.executor.worktree import proposed_changes, reviewed_commit
    from ract.review_hunks import ReviewStopped, proposed_hunks

    repo = harness.project_dir
    try:
        changes = proposed_changes(
            repo, record.parent_snapshot_before, record.parent_snapshot_after
        )
    except WorktreeError as exc:
        return Rooted(
            value=None,
            assumption=f"Step {index + 1}'s proposal can be listed.",
            confidence=0.0,
            provenance=["harness.substrate_adapter", f"step:{index + 1}", "review"],
            error=f"Step {index + 1}'s changes were not applied: {exc}",
            hint=f"see the step's commit on branch {record.branch}",
        )
    kept: dict[str, bytes | None] = {}
    try:
        for path, before, after in changes:
            turn_context.report(
                "diff.proposed",
                {
                    "path": path,
                    "hunks": proposed_hunks(path, before, after),
                    # A control or executable-configuration file is tier 2 (D3).
                    "tier": _path_tier(repo, path),
                },
            )
            decision = reviewer(path, before, after)
            for hunk_id, answer in sorted(decision.answers.items()):
                turn_context.report(
                    "diff.reviewed", {"path": path, "hunk": hunk_id, "decision": answer}
                )
            kept[path] = decision.content
    except ReviewStopped:
        return Rooted(
            value=None,
            assumption=f"Step {index + 1}'s proposal is reviewed.",
            confidence=0.0,
            provenance=["harness.substrate_adapter", f"step:{index + 1}", "review"],
            error=(
                f"The review of step {index + 1} ended without an answer; nothing "
                f"from it was applied (the proposal is on branch {record.branch})."
            ),
            hint="run the intent again to review it, or see that branch",
        )
    try:
        return Rooted(
            value=reviewed_commit(repo, record.parent_snapshot_after, kept),
            assumption="The commit holds what the operator kept.",
            confidence=1.0,
            provenance=["harness.substrate_adapter", f"step:{index + 1}", "review"],
        )
    except WorktreeError as exc:
        return Rooted(
            value=None,
            assumption=f"Step {index + 1}'s review can be recorded.",
            confidence=0.0,
            provenance=["harness.substrate_adapter", f"step:{index + 1}", "review"],
            error=f"Step {index + 1}'s changes were not applied: {exc}",
            hint=f"see the step's commit on branch {record.branch}",
        )


@dataclass(frozen=True)
class _ExecutorSucceeded:
    """Post-condition: the step's executor call returned a result.

    Reads the ``executor_ok`` flag the step runner puts in the snapshot's
    metadata. Has the two members ``SubstrateLoop._finalize`` uses.
    """

    required: bool = True

    def evaluate(self, snapshot: WorkspaceSnapshot) -> PredicateResult:
        if snapshot.metadata.get("executor_ok"):
            return PredicateResult(ok=True, reason="the step's executor call succeeded")
        error = str(snapshot.metadata.get("executor_error") or "")
        return PredicateResult(
            ok=False, reason=f"the step's executor call failed: {error[:200]}"
        )


_EXECUTOR_SUCCEEDED = _ExecutorSucceeded()


def _single_step_plan(plan: Plan, step: Step) -> Plan:
    """Return a fresh ``Plan`` carrying just ``step`` (parent plan's
    assumption / confidence preserved so the per-step executor path sees
    the same rooted context)."""
    return Plan(
        assumption=plan.assumption,
        confidence=plan.confidence,
        steps=[step],
    )


def _merge_reports(
    reports: list[ExecutionReport],
    intent: str,
    plan: Plan,
) -> ExecutionReport:
    """Aggregate per-step ``ExecutionReport`` values into one, preserving
    the shape callers downstream of ``Harness.run`` already handle."""
    step_results: list[Any] = []
    assumptions: list[str] = [plan.assumption]
    provenance: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    refusals: list[Any] = []
    unsigned: list[str] = []
    for rep in reports:
        step_results.extend(rep.step_results)
        for a in rep.assumptions:
            if a and a not in assumptions:
                assumptions.append(a)
        provenance.update(rep.provenance)
        artifacts.update(rep.artifacts)
        metrics.update(rep.metrics)
        refusals.extend(rep.refusals)
        unsigned.extend(rep.unsigned_artifacts)
    return ExecutionReport(
        intent=intent,
        step_results=step_results,
        assumptions=assumptions,
        provenance=provenance,
        artifacts=artifacts,
        plan=plan,
        metrics=metrics,
        refusals=refusals,
        unsigned_artifacts=unsigned,
    )


def _is_answer_step(step: Step) -> bool:
    """An answer step (B-042) names no file and calls no tool: it writes nothing."""
    return (
        not step.expected_artifact
        and step.tool_call is None
        and not getattr(step, "agent", False)  # B-137: it changes files
    )


def _snapshot_failure(exc: WorktreeError) -> Rooted[ExecutionReport]:
    """A repository check or snapshot that failed, as a failed result (package 5, H6)."""
    return Rooted(
        value=None,
        assumption="The working tree can be snapshotted before the steps run.",
        confidence=0.0,
        provenance=["harness.substrate_adapter", "snapshot"],
        error=str(exc),
        hint=(
            "close the program that has the file open, or make the file writable, "
            "then run the intent again"
        ),
    )


def run_via_substrate(
    harness: "Harness",
    intent: str,
    plan: Plan,
    *,
    context: str = "",
    approval_callback: Callable[[Step], bool] | None = None,
    stream: bool = False,
    stream_callback: Callable[[str], None] | None = None,
) -> Rooted[ExecutionReport]:
    """Run ``plan`` through the substrate and report each step's real outcome.

    H4 (package 4): a step's ``done`` is held until its files are applied. The
    loop releases it after a successful apply; any other exit releases the held
    step with the outcome its result implies (refused for a refused path, failed
    otherwise), so the step never reads done when the disk did not change.
    """
    executor = harness.executor
    executor.hold_step_report = True
    result: Rooted[ExecutionReport] | None = None
    try:
        result = _run_via_substrate_steps(
            harness,
            intent,
            plan,
            context=context,
            approval_callback=approval_callback,
            stream=stream,
            stream_callback=stream_callback,
        )
        return result
    finally:
        executor.hold_step_report = False
        if result is not None and result.is_ok():
            executor.release_held_step("done")
        else:
            error = (result.error if result is not None else None) or "the turn stopped"
            hint = result.hint if result is not None else None
            refused = "refused" in error or "left these paths" in error
            executor.release_held_step(
                "refused" if refused else "failed", hint or error
            )


def _run_via_substrate_steps(
    harness: "Harness",
    intent: str,
    plan: Plan,
    *,
    context: str = "",
    approval_callback: Callable[[Step], bool] | None = None,
    stream: bool = False,
    stream_callback: Callable[[str], None] | None = None,
) -> Rooted[ExecutionReport]:
    """Drive ``plan.steps`` through the ``SubstrateLoop``.

    Preconditions (checked by the caller before this function runs; see
    ``Harness.run``'s ``substrate_loop`` branch):

    - ``harness.project_dir`` is a git repository.
    - The working tree has no uncommitted tracked changes.
    - ``config.substrate_loop is True``.

    Failures inside a single step's transaction (post-condition
    ``ok=False``, unresolved handshake, commit failure) are surfaced as
    a ``Rooted`` error whose provenance names ``harness.substrate_adapter``
    and the step index; ``SubstrateLoop._finalize`` has already rolled
    back the offending worktree by the time this function inspects the
    ``StepRecord``.
    """
    # ---- preconditions ---------------------------------------------------
    # These are cheap and the caller re-checks them; asserting inside the
    # shim keeps the failure mode local rather than trusting a stale
    # caller check.
    try:
        ensure_git_repo(harness.project_dir)
    except WorktreeError as exc:
        return _snapshot_failure(exc)
    if all(_is_answer_step(step) for step in plan.steps):
        # LR:: A plan of answer steps writes nothing, so it needs no snapshot,
        # worktree, branch or commit (B-042). It reads the operator's files
        # where they are.
        harness.executor.step_number_offset = 0
        # Nothing is applied after these steps, so their reports are not held (H4).
        # The executor runs the whole plan in one call: held, each finished step
        # replaced the one before it and only the last was reported.
        harness.executor.hold_step_report = False
        return harness.executor.execute(
            intent,
            plan,
            context=context,
            approval_callback=approval_callback,
            stream=stream,
            stream_callback=stream_callback,
        )
    # S-011b: the first step's base is a snapshot of the working tree as it
    # is, uncommitted changes included, so a dirty tree (RACT's own earlier
    # turns leave one) keeps isolation instead of forcing the in-place path.
    # H6 (package 5): a repository check or snapshot that fails (a locked file, for one) is a
    # failed result with its sentence, not an exception that escapes the substrate.
    import shutil
    import time

    from ract.ui.workspace_screens import preparing_line, ready_line

    width = shutil.get_terminal_size((80, 24)).columns
    shows_workspace = getattr(harness.executor, "step_tools", None) is not None
    started = time.monotonic()
    if shows_workspace:
        # B-110 D6: the first visible line of a step that changes files, before
        # the snapshot and the worktree (MASON's preparing line, L-298 item 5).
        print(preparing_line(0, width), flush=True)
    try:
        snapshot = take_snapshot(
            harness.project_dir, progress=lambda line: print(line, flush=True)
        )
    except WorktreeError as exc:
        return _snapshot_failure(exc)
    if shows_workspace:
        print(ready_line(time.monotonic() - started, width), flush=True)
    parent_snapshot = snapshot.sha
    if snapshot.left_out:
        print(snapshot.notice(), flush=True)
    applied_so_far: list[str] = []
    created_by_run: set[str] = set()

    loop = SubstrateLoop(
        repo_root=harness.project_dir,
        parent_snapshot=parent_snapshot,
        worktree_manager=WorktreeManager(harness.project_dir),
        # S-011: never move the operator's branch. Each step's commit stays
        # on its rootact/step/* branch; its changes reach the working tree
        # through apply_commit_to_working_tree below.
        advance_head=False,
        # container_backend / sandbox_backend / manifest deliberately
        # omitted — the shim keeps the legacy Executor.execute semantics
        # while adding worktree isolation. Module_03's sandbox path
        # attaches those separately when the run is under a manifest.
    )

    per_step_reports: list[ExecutionReport] = []

    for index, step in enumerate(plan.steps):
        if run_checkpoint.already_finished(index + 1):
            continue  # done before the run was interrupted (D13)
        if plan_gate.is_skipped(index + 1):
            harness.executor.report_skipped(index + 1, step)
            continue
        if turn_context.cancelled():
            # Checked before the step's worktree and branch exist, so an
            # interrupted turn leaves no step branch behind (G-027).
            return Rooted(
                value=None,
                assumption="The turn was not interrupted before this step began.",
                confidence=0.0,
                provenance=["harness.substrate_adapter", f"step:{index + 1}"],
                error=(
                    f"Interrupted before step {index + 1}. Already applied to your "
                    "files in this run: "
                    + (", ".join(applied_so_far) or "nothing")
                    + "."
                ),
                hint="interrupted",
            )
        single_plan = _single_step_plan(plan, step)
        if _is_answer_step(step):
            # Runs in the operator's tree, after the earlier steps' changes
            # were applied there, so the answer sees them (B-042).
            harness.executor.step_number_offset = index
            answered = harness.executor.execute(
                intent,
                single_plan,
                context=context,
                approval_callback=approval_callback,
                stream=stream,
                stream_callback=stream_callback,
            )
            if not answered.is_ok():
                return answered
            per_step_reports.append(answered.unwrap())
            harness.executor.release_held_step("done")
            continue
        # Acceptance post-conditions are the responsibility of module_01's
        # compiled AcceptanceSuite; the shim adds only one: the executor
        # call succeeded. Without it SubstrateLoop._finalize committed
        # whenever the runner returned, so a failed or interrupted step
        # left an empty "rootact step" commit on a branch that nothing
        # cleaned up (G-033). A failed post-condition rolls the step back
        # and deletes its branch.
        spec = SubstrateStepSpec(
            predicates=(_EXECUTOR_SUCCEEDED,),
            budget=ResourceBudget(
                wall_seconds=int(
                    harness.config.get("substrate_loop_step_wall_seconds", 60)
                ),
            ),
            commit_message=f"rootact step {index + 1}: {step.action}"[:120],
        )

        captured: dict[str, Rooted[ExecutionReport]] = {}

        def step_runner(worktree, container_ref):  # noqa: ARG001
            # Each executor call sees a one-step plan; the offset keeps the
            # session's step numbers those of the whole plan.
            harness.executor.step_number_offset = index
            # Writes in the step's worktree are not changes to the operator's
            # files; the apply below records what reaches them.
            # The executor finishing in the worktree is not the step
            # finishing for the run's checkpoint: that waits for the apply.
            with (
                turn_context.recording_suspended(),
                run_checkpoint.finish_deferred(),
                _rebind_project_dir(harness.executor, worktree.path),
            ):
                per_step_rooted = harness.executor.execute(
                    intent,
                    single_plan,
                    context=context,
                    approval_callback=approval_callback,
                    stream=stream,
                    stream_callback=stream_callback,
                )
            captured["result"] = per_step_rooted
            # A workspace snapshot is required so the loop's post-condition
            # evaluator has something to consult. The shim populates only
            # the metadata channel — the empty ``files`` dict is intentional
            # (no shim post-conditions declared → no file oracle needed).
            return WorkspaceSnapshot(
                files={},
                metadata={
                    "executor_ok": per_step_rooted.is_ok(),
                    "executor_error": per_step_rooted.error or "",
                    "substrate_adapter": True,
                },
            )

        # D13: the step and its worktree are recorded before either exists,
        # so a resumed run can remove them.
        run_checkpoint.step_started(index + 1)
        run_checkpoint.note_worktree(spec.step_id.hex())
        record = loop.run_step(spec, step_runner)

        result = captured.get("result")
        if result is None:
            # step_runner never ran (e.g., depends_on gate short-circuit
            # inside SubstrateLoop.run_step). Surface as a Rooted error.
            return Rooted(
                value=None,
                assumption=(
                    "substrate adapter routes each plan step through a "
                    "worktree-scoped StepTransaction."
                ),
                confidence=0.0,
                provenance=["harness.substrate_adapter", f"step:{index + 1}"],
                error=(
                    f"Step {index + 1} did not run inside its transaction "
                    f"(outcome={record.outcome.name}): {record.reason}"
                ),
            )

        if not result.is_ok():
            # Executor already returned an error; the loop has already
            # rolled back the worktree. Bubble the error up unchanged so
            # callers downstream see the same shape they would have
            # received from a legacy Executor.execute failure.
            return result

        if record.outcome is TransactionOutcome.ROLLED_BACK:
            # Executor succeeded but the loop rolled back (post-condition
            # or commit failure). Convert to a Rooted error naming the
            # step so ``Harness.run``'s failure path is uniform.
            return Rooted(
                value=None,
                assumption=("each substrate step commits on post-condition success."),
                confidence=0.0,
                provenance=["harness.substrate_adapter", f"step:{index + 1}"],
                error=(
                    f"Step {index + 1} rolled back after execution: {record.reason}"
                ),
            )

        apply_to = record.parent_snapshot_after
        reviewer = getattr(harness.executor, "proposed_reviewer", None)
        if reviewer is not None and apply_to != record.parent_snapshot_before:
            reviewed = _review_proposed(harness, reviewer, record, index)
            if not reviewed.is_ok():
                return reviewed
            apply_to = reviewed.unwrap()
        with turn_context.persisting() as allowed:
            if allowed:
                outcome = apply_commit_to_working_tree(
                    harness.project_dir,
                    record.parent_snapshot_before,
                    apply_to,
                    created_by_run=frozenset(created_by_run),
                    left_out=frozenset(snapshot.left_out),
                )
        if not allowed:
            # The step committed on its own branch while the turn was being
            # interrupted. Do not touch the working tree.
            return Rooted(
                value=None,
                assumption="The turn was not interrupted before its changes were applied.",
                confidence=0.0,
                provenance=["harness.substrate_adapter", f"step:{index + 1}"],
                error=(
                    f"Interrupted; step {index + 1}'s changes were not applied to "
                    f"your files (they are on branch {record.branch})."
                ),
                hint="interrupted",
            )
        created_by_run.update(outcome.added)
        applied_so_far.extend(outcome.applied)
        if outcome.applied:
            # The step's base snapshot, kept as this turn's checkpoint (B-110 D6).
            undo_backup.keep_base(harness.project_dir, record.parent_snapshot_before)
        if reviewer is not None:
            turn_context.report(
                "change.applied",
                {
                    "paths": list(outcome.applied),
                    "checkpoint": undo_backup.current_backup_id() or "",
                    "skipped": [
                        {"path": p, "reason": why} for p, why in outcome.skipped.items()
                    ],
                    # L-298 item 2: where the skipped paths' changes were saved.
                    "patch": outcome.patch_path,
                },
            )
        turn_context.record_written(harness.project_dir, outcome.applied)
        if outcome.skipped:
            left = "; ".join(f"{p} ({why})" for p, why in outcome.skipped.items())
            where = (
                f" The step's changes for them are in {outcome.patch_path}."
                if outcome.patch_path
                else ""
            )
            return Rooted(
                value=None,
                assumption=(
                    f"Step {index + 1}'s changes can be applied without touching "
                    "anything already in the working tree."
                ),
                confidence=0.0,
                provenance=["harness.substrate_adapter", f"step:{index + 1}"],
                error=(
                    f"Step {index + 1} left these paths as they are: {left}.{where} "
                    "Already applied to your files in this run: "
                    + (", ".join(applied_so_far) or "nothing")
                    + "."
                ),
                hint=(
                    (
                        f"Review {outcome.patch_path} and apply it with `git apply`, or "
                        if outcome.patch_path
                        else ""
                    )
                    + f"see the step's full commit on branch {record.branch}."
                ),
            )

        run_checkpoint.step_finished(index + 1)
        per_step_reports.append(result.unwrap())
        harness.executor.release_held_step("done")

    merged = _merge_reports(per_step_reports, intent, plan)
    return Rooted(
        value=merged,
        assumption=(
            "every plan step ran inside its own worktree transaction and "
            "committed via SubstrateLoop._finalize."
        ),
        confidence=1.0,
        provenance=["harness.substrate_adapter"],
    )


__all__ = ["run_via_substrate"]

# RACT 0.4.0
