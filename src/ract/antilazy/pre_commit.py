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

from ract.antilazy.mutation import (
    DEFAULT_KILL_THRESHOLD,
    EquivalenceDetector,
    KillEvaluator,
    MutantSource,
    MutationReport,
    run_mutation,
)

if TYPE_CHECKING:
    from ract.core.predicate import AcceptanceSuite
    from ract.core.transaction import StepTransaction


@dataclass(frozen=True)
class GateOutcome:
    """Result of running a pre-commit gate on a step transaction."""

    passed: bool
    should_roll_back: bool
    report: MutationReport


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


# RACT 0.4.0
