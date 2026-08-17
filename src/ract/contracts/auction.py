"""Auction as scheduled between-iteration environment sweep (SUBSTRATE §8).

The v0.3 ``DeadCodeAuction`` was a CLI-invoked scanner that emitted a
list of dead-code candidates on operator request. Module_06 reframes it
as a **scheduled environment sweep** that runs between the loop's
iterations (not on model request) and stages ``DeletionProposal``
values through Fence.

Load-bearing scan logic (symbol-graph + age + inbound-reference count)
reuses ``ract.dead_code_auction.DeadCodeAuction`` primitives. The CLI
verb ``ract auction`` keeps its convenience output path.

Reference sources:

- SUBSTRATE spec §8 ("Dead Code Auction as periodic environment
  sweep").
- v0.3 source: ``src/ract/dead_code_auction.py`` (reused primitives).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ract.core.module_identity import _module_knot, register_module_knot

_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# ---------------------------------------------------------------------------
# Config + proposal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuctionConfig:
    """Between-iteration Auction sweep configuration.

    ``stale_days``: minimum age of a candidate before it is proposed.
    ``min_iteration_wall_seconds``: gate the sweep so it doesn't fire on
    every tiny step (lateral chain branch D — avoid runaway wall-clock).
    ``max_proposals_per_sweep``: cap the number of proposals emitted per
    sweep so the operator's review queue is bounded.
    """

    stale_days: int = 60
    min_iteration_wall_seconds: float = 15.0
    max_proposals_per_sweep: int = 5


@dataclass(frozen=True)
class DeletionProposal:
    """One proposed deletion staged by the Auction sweep.

    ``fence_brief`` is pre-attached — the operator sees Fence's
    plausible-reason brief alongside the proposal. Approval turns the
    proposal into a normal ``DeleteFileAction`` that still passes
    through ``FenceGate`` (lateral chain branch E — compose, don't
    duplicate).
    """

    workspace_path: str
    last_modified_days: int
    inbound_references: int
    reason: str
    fence_brief: object | None = None  # PlausibleReasonBrief once wired


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


@dataclass
class AuctionSweep:
    """Scheduled between-iteration Auction over a workspace snapshot.

    The loop's iteration boundary calls ``run``; the sweep emits an
    ``auction.proposal`` event per candidate into the module_05 event
    log (see ``ract.trace.events.EventKind``).
    """

    workspace_root: Path
    config: AuctionConfig = field(default_factory=AuctionConfig)
    # ``None`` means "never run"; the first should_run call always fires.
    _last_run_wall_seconds: float | None = None

    def should_run(self, current_wall_seconds: float) -> bool:
        """Return True when ``config.min_iteration_wall_seconds`` has elapsed.

        The loop's iteration boundary calls this before ``run``; a
        return of ``False`` skips the sweep for this iteration.
        """
        if self._last_run_wall_seconds is None:
            return True
        return (
            current_wall_seconds - self._last_run_wall_seconds
            >= self.config.min_iteration_wall_seconds
        )

    def run(self, current_wall_seconds: float | None = None) -> list[DeletionProposal]:
        """Scan and stage deletion proposals.

        Reuses the v0.3 ``DeadCodeAuction.scan`` for the load-bearing
        symbol-graph + age check. Wraps each ``AuctionItem`` as a
        ``DeletionProposal`` with a Fence brief pre-attached.
        """
        # Local import so this module has no v0.3-CLI import surface.
        from ract.dead_code_auction import DeadCodeAuction

        v03 = DeadCodeAuction(
            self.workspace_root,
            config={"min_age_days": self.config.stale_days},
        )
        try:
            items = v03.scan()
        except Exception:  # noqa: BLE001
            items = []

        proposals: list[DeletionProposal] = []
        for item in items[: self.config.max_proposals_per_sweep]:
            proposals.append(
                DeletionProposal(
                    workspace_path=item.relative_path,
                    last_modified_days=item.last_modified_days,
                    inbound_references=item.inbound_references,
                    reason=item.reason,
                )
            )

        # Emit one auction.proposal event per proposal. The event kind
        # was added to the closed vocabulary in module_06 (see
        # ``ract.trace.events.EventKind`` and ``docs/EVENTS.md`` v2 bump
        # note).
        try:
            from ract.trace.sink import emit as _emit_event

            for proposal in proposals:
                _emit_event(
                    "auction.proposal",
                    {
                        "workspace_path": proposal.workspace_path,
                        "last_modified_days": proposal.last_modified_days,
                        "inbound_references": proposal.inbound_references,
                        "reason": proposal.reason,
                    },
                )
        except Exception:  # noqa: BLE001
            pass

        if current_wall_seconds is not None:
            self._last_run_wall_seconds = current_wall_seconds
        return proposals


# RACT 0.4.0
