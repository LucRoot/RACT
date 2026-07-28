"""Auction as scheduled between-iteration environment sweep."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ract.contracts.auction import AuctionConfig, AuctionSweep, DeletionProposal
from ract.trace.events import LEGAL_EVENT_KINDS


def test_auction_proposal_kind_is_registered() -> None:
    """module_06 added ``auction.proposal`` to the closed vocabulary."""
    assert "auction.proposal" in LEGAL_EVENT_KINDS


def test_auction_produces_proposals_not_deletions() -> None:
    """Sweep returns ``DeletionProposal`` values; nothing is deleted."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        sweep = AuctionSweep(
            workspace_root=ws,
            config=AuctionConfig(
                stale_days=0,
                min_iteration_wall_seconds=0.0,
                max_proposals_per_sweep=3,
            ),
        )
        proposals = sweep.run(current_wall_seconds=10.0)
        assert isinstance(proposals, list)
        for p in proposals:
            assert isinstance(p, DeletionProposal)


def test_auction_runs_between_iterations() -> None:
    """``should_run`` gates the sweep on ``min_iteration_wall_seconds``."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        sweep = AuctionSweep(
            workspace_root=ws,
            config=AuctionConfig(
                stale_days=0,
                min_iteration_wall_seconds=15.0,
                max_proposals_per_sweep=3,
            ),
        )
        # No prior run; should_run must be true at first call.
        assert sweep.should_run(0.0)
        sweep.run(current_wall_seconds=0.0)
        # 5 seconds later — under the 15s gate.
        assert not sweep.should_run(5.0)
        # 20 seconds later — over the 15s gate.
        assert sweep.should_run(20.0)


def test_auction_respects_max_proposals_cap() -> None:
    """``max_proposals_per_sweep`` caps the returned list."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        sweep = AuctionSweep(
            workspace_root=ws,
            config=AuctionConfig(
                stale_days=0,
                min_iteration_wall_seconds=0.0,
                max_proposals_per_sweep=2,
            ),
        )
        proposals = sweep.run(current_wall_seconds=1.0)
        assert len(proposals) <= 2


# RACT 0.4.0
