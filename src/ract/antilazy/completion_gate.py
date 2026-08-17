"""ALM completion-path gates — G7 companion + G8 effort reconciliation.

These wire G7 and G8 to a T1-completion callback. The substrate
``LoopController`` calls ``run_completion_gates`` after ``check_t1``
returns ``COMPLETE``; a non-empty return blocks the COMPLETE and
queues a resume prompt for the next iteration.

Keeping the wiring here (rather than inline in ``loop_controller``)
keeps the substrate loop free of ALM imports at module load time; the
loop imports this module lazily when a ``CompanionBundle`` or an
``EffortEstimate`` is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ract.antilazy.companion import (
    CompanionAdapter,
    CompanionConfig,
    CompanionProviderCollisionError,
    CompanionRedTeamReport,
    CounterexampleRunner,
    run_companion,
)
from ract.antilazy.effort import (
    EffortActual,
    EffortEstimate,
    EffortReconciliation,
    measure_actual_effort,
    reconcile_effort,
    suspicion_prompt_text,
)

if TYPE_CHECKING:
    from ract.antilazy.patchdiff import Patch
    from ract.core.predicate import AcceptanceSuite
    from ract.providers.provider import Provider


@dataclass(frozen=True)
class CompanionBundle:
    """Everything the loop needs to schedule G7 at T1 completion.

    ``primary`` is the primary provider of the current step; the
    different-provider constraint runs against ``recent_history`` plus
    ``primary.name``. ``pre_change_workspace`` / ``post_change_workspace``
    are the snapshots the ``runner`` evaluates each counterexample on.
    """

    adapter: CompanionAdapter
    config: CompanionConfig
    primary: "Provider"
    recent_history: tuple[str, ...] = field(default_factory=tuple)
    runner: CounterexampleRunner | None = None


@dataclass(frozen=True)
class CompletionGateOutcome:
    """Aggregate result of G7 + G8 on a completion attempt.

    - ``blocks_complete`` is True when the loop must NOT terminate
      COMPLETE this iteration. Callers read this as the signal to
      queue the resume prompt.
    - ``resume_prompt`` is the string to inject into the next planning
      turn. Empty when neither gate blocked.
    - ``companion_report`` is the G7 report (may be None if G7 was not
      configured). ``companion_provider_collision`` is True when the
      companion could not be scheduled because of the
      different-provider constraint; the loop treats that as blocking
      COMPLETE for a run whose deployment mode is ``multi_provider``.
    - ``effort_reconciliation`` is the G8 report (may be None if the
      caller did not provide an estimate).
    """

    blocks_complete: bool
    resume_prompt: str
    companion_report: CompanionRedTeamReport | None = None
    companion_provider_collision: bool = False
    effort_reconciliation: EffortReconciliation | None = None


def run_completion_gates(
    *,
    intent: str,
    final_diff: "Patch",
    visible_suite: "AcceptanceSuite",
    companion_bundle: CompanionBundle | None = None,
    effort_estimate: EffortEstimate | None = None,
    pre_change_workspace: object | None = None,
    post_change_workspace: object | None = None,
    symgraph: object | None = None,
) -> CompletionGateOutcome:
    """Run G7 (companion) and G8 (effort reconciliation).

    Returns a ``CompletionGateOutcome`` the caller reads to decide
    whether to hold COMPLETE and queue a resume prompt.
    """
    resume_parts: list[str] = []
    companion_report: CompanionRedTeamReport | None = None
    companion_collision = False
    effort_recon: EffortReconciliation | None = None
    blocks_complete = False

    # G7 — companion red team.
    if companion_bundle is not None:
        try:
            companion_report = run_companion(
                intent=intent,
                diff=final_diff,
                visible_suite=visible_suite,
                config=companion_bundle.config,
                adapter=companion_bundle.adapter,
                runner=companion_bundle.runner,
                pre_change_workspace=pre_change_workspace,
                post_change_workspace=post_change_workspace,
                primary=companion_bundle.primary,
                recent_history=companion_bundle.recent_history,
            )
        except CompanionProviderCollisionError as exc:
            companion_collision = True
            # multi_provider mode: collision blocks the completion path
            # so a lazy operator cannot get around G7 by silently
            # scheduling the same provider on both sides.
            if companion_bundle.config.deployment_mode == "multi_provider":
                blocks_complete = True
                resume_parts.append(
                    f"[COMPANION COLLISION] {exc}. Register a different "
                    "companion provider or opt into "
                    '``deployment_mode="single_provider_advisory"``. G7 '
                    "did not run this iteration."
                )
        if companion_report is not None:
            survivors = companion_report.surviving_findings()
            if survivors:
                blocks_complete = True
                sample = survivors[0]
                resume_parts.append(
                    "[COMPANION COUNTEREXAMPLES] the companion produced "
                    f"{len(survivors)} counterexample(s) that pass on the "
                    "pre-change workspace and fail on the post-change "
                    "workspace. Sample: "
                    f"{sample.test_id} - {sample.description}. "
                    "Extend the diff so each counterexample passes on "
                    "post-change too."
                )

    # G8 — effort reconciliation.
    if effort_estimate is not None:
        # symgraph is typed ``object | None`` on the outer signature so
        # this module does not need to import SymbolGraph; the effort
        # reconciler accepts it and defaults gracefully when unset.
        realized: EffortActual = measure_actual_effort(final_diff, graph=symgraph)  # type: ignore[arg-type]
        effort_recon = reconcile_effort(effort_estimate, realized)
        if effort_recon.anomalies:
            blocks_complete = True
            resume_parts.append(suspicion_prompt_text(effort_recon))
            _emit_effort_anomaly_event(effort_recon)

    return CompletionGateOutcome(
        blocks_complete=blocks_complete,
        resume_prompt="\n\n".join(p for p in resume_parts if p),
        companion_report=companion_report,
        companion_provider_collision=companion_collision,
        effort_reconciliation=effort_recon,
    )


def _emit_effort_anomaly_event(recon: EffortReconciliation) -> None:
    """Best-effort emit of a ``laziness.violated`` event for G8."""
    try:  # local import breaks the trace→antilazy cycle
        from ract.trace.sink import emit as _emit_event

        _emit_event(
            "laziness.violated",
            {
                "kind": "effort_below_expected",
                "anomalies": list(recon.anomalies),
                "tau_effort": recon.tau_effort,
                "ratio": {k: round(v, 4) for k, v in recon.ratio.items()},
                "estimate_source": recon.estimate.estimate_source,
            },
        )
    except Exception:  # noqa: BLE001 — never fail on trace error
        pass


__all__ = [
    "CompanionBundle",
    "CompletionGateOutcome",
    "run_completion_gates",
]


# RACT 0.4.0
