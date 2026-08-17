"""Pin the numeric output of ``_lr_signature_seed``.

Milestone-oracle ``signed_confidence`` mixes this seed. A subtle
refactor of the underlying expression would rescale every downstream
confidence value; the lock catches that drift. If the seed is
intentionally changed, update the constant here in the same commit.
"""

from __future__ import annotations

import pytest

from ract.milestone_oracle import _lr_signature_seed


LOCKED_SEED_VALUE = 0.1636


def test_lr_signature_seed_is_locked() -> None:
    # abs=1e-5 is tighter than the smallest single-character mutation
    # of the source string (a one-ordinal shift moves the seed by
    # 1/10000 = 1e-4), so any real drift trips the lock while
    # floating-point noise stays well inside the window.
    assert _lr_signature_seed() == pytest.approx(LOCKED_SEED_VALUE, abs=1e-5)
