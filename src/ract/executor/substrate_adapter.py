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

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)

from ract.core.loop import WorkspaceSnapshot
from ract.core.transaction import ResourceBudget, TransactionOutcome
from ract.executor.loop import SubstrateLoop, SubstrateStepSpec
from ract.executor.steps import ExecutionReport, Executor
from ract.executor.worktree import (
    WorktreeManager,
    ensure_clean_tracked_tree,
    ensure_git_repo,
    resolve_head_sha,
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
    try:
        executor.project_dir = new_path
        for helper, _original in originals:
            helper.project_dir = new_path
        yield
    finally:
        executor.project_dir = original_project_dir
        for helper, original in originals:
            helper.project_dir = original


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
    for rep in reports:
        step_results.extend(rep.step_results)
        for a in rep.assumptions:
            if a and a not in assumptions:
                assumptions.append(a)
        provenance.update(rep.provenance)
        artifacts.update(rep.artifacts)
        metrics.update(rep.metrics)
        refusals.extend(rep.refusals)
    return ExecutionReport(
        intent=intent,
        step_results=step_results,
        assumptions=assumptions,
        provenance=provenance,
        artifacts=artifacts,
        plan=plan,
        metrics=metrics,
        refusals=refusals,
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
    ensure_git_repo(harness.project_dir)
    ensure_clean_tracked_tree(harness.project_dir)
    parent_snapshot = resolve_head_sha(harness.project_dir)

    loop = SubstrateLoop(
        repo_root=harness.project_dir,
        parent_snapshot=parent_snapshot,
        worktree_manager=WorktreeManager(harness.project_dir),
        # container_backend / sandbox_backend / manifest deliberately
        # omitted — the shim keeps the legacy Executor.execute semantics
        # while adding worktree isolation. Module_03's sandbox path
        # attaches those separately when the run is under a manifest.
    )

    per_step_reports: list[ExecutionReport] = []

    for index, step in enumerate(plan.steps):
        single_plan = _single_step_plan(plan, step)
        # Per-step post-conditions are the responsibility of module_01's
        # compiled AcceptanceSuite; the shim does not synthesize any
        # here. Post-conditions default to () → SubstrateLoop._finalize
        # commits unconditionally when the runner returns without
        # raising.
        spec = SubstrateStepSpec(
            predicates=(),
            budget=ResourceBudget(
                wall_seconds=int(
                    harness.config.get("substrate_loop_step_wall_seconds", 60)
                ),
            ),
            commit_message=f"rootact step {index + 1}: {step.action}"[:120],
        )

        captured: dict[str, Rooted[ExecutionReport]] = {}

        def step_runner(worktree, container_ref):  # noqa: ARG001
            with _rebind_project_dir(harness.executor, worktree.path):
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

        per_step_reports.append(result.unwrap())

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
