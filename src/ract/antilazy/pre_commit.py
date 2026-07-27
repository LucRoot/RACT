"""ALM pre-commit gate that runs G2 on a ``StepTransaction``.

The substrate ``StepTransaction.post_conditions`` is a frozen tuple of
``AcceptancePredicate`` values (see ``ract.core.transaction``). G2 is
not a predicate; it is a run over the touched surface that produces a
``MutationReport``. Rather than extend ``AcceptancePredicate`` to
carry a heterogeneous verdict, this module exposes an ``enforce_g2``
helper the pre-commit path calls before it commits the worktree.

Below-threshold ``kill_rate`` returns ``GateOutcome(passed=False,
should_roll_back=True, report=…)`` and emits ``laziness.violated``
with ``kind="mutation_kill_below_threshold"``. The caller is
responsible for the actual git-worktree rollback; this module is pure
over its inputs so tests can drive it without a live worktree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ract.antilazy.coverage import (
    DEFAULT_DELTA_MUT,
    DEFAULT_TAU_COV,
    CoverageDeltaReport,
    run_coverage_delta,
)
from ract.antilazy.mutation import (
    DEFAULT_KILL_THRESHOLD,
    EquivalenceDetector,
    KillEvaluator,
    MutantSource,
    MutationReport,
    run_mutation,
)
from ract.antilazy.patchdiff import (
    DEFAULT_FLAKINESS_RUNS,
    DEFAULT_MAX_DIFFERENTIATORS_PER_TRANSACTION,
    DEFAULT_MAX_PER_FUNCTION,
    BaselineKind,
    DifferentiatorGenerator,
    Patch,
    PatchDifferentiationReport,
    RetrievalIndex,
    TestRunner,
    run_patchdiff,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ract.core.loop import WorkspaceSnapshot
    from ract.core.predicate import AcceptanceSuite
    from ract.core.transaction import StepTransaction


@dataclass(frozen=True)
class GateOutcome:
    """Result of running a pre-commit gate on a step transaction."""

    passed: bool
    should_roll_back: bool
    report: MutationReport


@dataclass(frozen=True)
class PatchDiffGateOutcome:
    """Result of running G3 on a step transaction."""

    passed: bool
    should_roll_back: bool
    report: PatchDifferentiationReport


@dataclass(frozen=True)
class CoverageDeltaGateOutcome:
    """Result of running G4 on a step transaction."""

    passed: bool
    should_roll_back: bool
    report: CoverageDeltaReport


def enforce_g2(
    transaction: "StepTransaction",
    suite: "AcceptanceSuite",
    *,
    touched_files: tuple[str, ...],
    source: MutantSource,
    evaluator: KillEvaluator,
    detector: EquivalenceDetector | None = None,
    threshold: float = DEFAULT_KILL_THRESHOLD,
) -> GateOutcome:
    """Run G2 against ``transaction``'s touched surface.

    Returns a ``GateOutcome`` describing whether the transaction
    should commit or roll back. Best-effort emit of
    ``laziness.violated`` on below-threshold kill rate; the emit is
    guarded so a missing trace writer does not fail the gate.
    """
    report = run_mutation(
        touched_files=touched_files,
        suite=suite,
        source=source,
        evaluator=evaluator,
        detector=detector,
        threshold=threshold,
    )
    if report.passed():
        return GateOutcome(passed=True, should_roll_back=False, report=report)
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "mutation_kill_below_threshold",
                "step_id": transaction.step_id.hex(),
                "branch": transaction.branch_name,
                "kill_rate": report.kill_rate,
                "threshold": report.threshold,
                "mutants_total": report.mutants_total,
                "mutants_killed": report.mutants_killed,
                "mutants_survived_count": len(report.mutants_survived),
                "mutants_equivalent_count": len(report.mutants_equivalent),
                # A sampled survivor id helps the operator triage
                # without pulling the whole survivor list into the
                # event payload.
                "sample_survivor": (
                    report.mutants_survived[0] if report.mutants_survived else ""
                ),
            },
            step_id=transaction.step_id,
        )
    except Exception:  # noqa: BLE001 — never fail the gate on trace error
        pass
    return GateOutcome(passed=False, should_roll_back=True, report=report)


def enforce_g3(
    transaction: "StepTransaction",
    patch: Patch,
    workspace_root: "Path",
    *,
    generator: DifferentiatorGenerator,
    runner: TestRunner,
    baseline: Patch | None = None,
    baseline_kind: BaselineKind = "null",
    retrieval_index: RetrievalIndex | None = None,
    total_budget: int = DEFAULT_MAX_DIFFERENTIATORS_PER_TRANSACTION,
    per_function_cap: int = DEFAULT_MAX_PER_FUNCTION,
    flakiness_runs: int = DEFAULT_FLAKINESS_RUNS,
) -> PatchDiffGateOutcome:
    """Run G3 against ``patch``; emit ``laziness.violated`` on failure.

    Failure modes:

    - ``is_semantic_noop`` — the diff touched functions but no
      differentiator distinguishes it from the baseline. Emit with
      ``kind="semantic_noop"``.
    - ``leakage_matches`` non-empty — a hunk byte-matches a prior
      commit or retrieval-index entry above the floor. Emit with
      ``kind="solution_leakage"``.
    """
    report = run_patchdiff(
        patch,
        workspace_root,
        generator=generator,
        runner=runner,
        baseline=baseline,
        baseline_kind=baseline_kind,
        retrieval_index=retrieval_index,
        total_budget=total_budget,
        per_function_cap=per_function_cap,
        flakiness_runs=flakiness_runs,
    )
    if not report.is_semantic_noop and not report.leakage_matches:
        return PatchDiffGateOutcome(
            passed=True, should_roll_back=False, report=report
        )
    kind = (
        "solution_leakage" if report.leakage_matches else "semantic_noop"
    )
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": kind,
                "step_id": transaction.step_id.hex(),
                "branch": transaction.branch_name,
                "patch_digest": report.patch_digest,
                "baseline_kind": report.baseline_kind,
                "generated_tests": report.generated_tests,
                "tests_that_distinguish": report.tests_that_distinguish,
                "leakage_matches": list(report.leakage_matches),
                "leakage_below_floor": report.leakage_below_floor,
                "retrieval_index_absent": report.retrieval_index_absent,
            },
            step_id=transaction.step_id,
        )
    except Exception:  # noqa: BLE001
        pass
    return PatchDiffGateOutcome(
        passed=False, should_roll_back=True, report=report
    )


def enforce_g4(
    transaction: "StepTransaction",
    patch: Patch,
    parent_snapshot: "WorkspaceSnapshot",
    child_snapshot: "WorkspaceSnapshot",
    *,
    mutation_report_parent: MutationReport | None = None,
    mutation_report_child: MutationReport | None = None,
    tau_cov: float = DEFAULT_TAU_COV,
    delta_mut: float = DEFAULT_DELTA_MUT,
) -> CoverageDeltaGateOutcome:
    """Run G4 against ``patch``; emit ``laziness.violated`` on failure.

    Failure fires when ``coverage_ratio < tau_cov`` OR (the change is
    non-trivial AND ``mutation_coverage_delta < delta_mut``). Emits
    with ``kind="coverage_delta_insufficient"``.
    """
    report = run_coverage_delta(
        parent_snapshot,
        child_snapshot,
        patch,
        mutation_report_parent=mutation_report_parent,
        mutation_report_child=mutation_report_child,
        tau_cov=tau_cov,
        delta_mut=delta_mut,
    )
    if report.passed():
        return CoverageDeltaGateOutcome(
            passed=True, should_roll_back=False, report=report
        )
    try:
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "coverage_delta_insufficient",
                "step_id": transaction.step_id.hex(),
                "branch": transaction.branch_name,
                "coverage_ratio": report.coverage_ratio,
                "tau_cov": report.tau_cov,
                "mutation_coverage_delta": report.mutation_coverage_delta,
                "delta_mut": report.delta_mut,
                "lines_new": report.lines_new,
                "lines_new_covered": report.lines_new_covered,
                "is_trivial_change": report.is_trivial_change,
                "coverage_ok": report.coverage_ok(),
                "mutation_ok": report.mutation_ok(),
            },
            step_id=transaction.step_id,
        )
    except Exception:  # noqa: BLE001
        pass
    return CoverageDeltaGateOutcome(
        passed=False, should_roll_back=True, report=report
    )


# RACT 0.4.0
