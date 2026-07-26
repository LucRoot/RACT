"""Environment-enforced contracts (SUBSTRATE §8).

v0.3 shipped Whisperer, Fence, and Auction as CLI features (see
``src/ract/legacy_whisperer.py``, ``src/ract/chestertons_fence.py``,
``src/ract/dead_code_auction.py``). v0.4 module_06 reframes them as
**contracts the environment enforces**, not features the model can
opt out of:

- ``WhispererContract`` runs *before* every planner call and injects a
  ``DialectBrief`` into the prompt template.
- ``FenceGate`` intercepts *every* ``DeleteFileAction`` before the
  transaction opens. The transaction opener refuses a delete action
  that hasn't passed through Fence.
- ``AuctionSweep`` runs *between* iterations on the loop's own schedule
  and stages ``DeletionProposal`` values for operator sign-off.

The load-bearing scan / graph / blame logic is reused from the v0.3
modules; this package provides the environment-enforced call sites. The
CLI verbs (``ract whisper``, ``ract fence``, ``ract auction``) remain
as convenience surfaces backed by the same primitives.

Reference sources:

- SUBSTRATE spec §8 (Whisperer, Fence, and Auction as Contracts).
- v0.3 Whisperer, Fence, and Auction implementations under
  ``src/ract/legacy_whisperer.py``, ``src/ract/chestertons_fence.py``,
  ``src/ract/dead_code_auction.py`` (the reused primitives).
"""

from ract.contracts.auction import (
    AuctionConfig,
    AuctionSweep,
    DeletionProposal,
)
from ract.contracts.fence import FenceGate, FenceOutcome, PlausibleReasonBrief
from ract.contracts.whisperer import DialectBrief, WhispererContract

__all__ = [
    "AuctionConfig",
    "AuctionSweep",
    "DeletionProposal",
    "DialectBrief",
    "FenceGate",
    "FenceOutcome",
    "PlausibleReasonBrief",
    "WhispererContract",
]

# RACT 0.4.0
