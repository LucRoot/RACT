"""Golden-hash lock over ``src/ract``.

Any change to a ``.py`` or ``.json`` file inside ``src/ract`` flips
this scalar. The test fails until an operator consciously re-locks
via ``ract source-digest --lock``. This forces the source surface to
be signed off, not silently drifted.
"""

from __future__ import annotations

from ract.source_digest import GOLDEN_HASH_CONSTANT, compute_golden_hash


def test_golden_hash_matches_locked() -> None:
    current = compute_golden_hash()
    assert current == GOLDEN_HASH_CONSTANT, (
        "src/ract source-tree digest differs from the locked value. "
        "If the change is intentional, run `ract source-digest --lock` "
        "and commit the updated GOLDEN_HASH_CONSTANT in the same commit. "
        f"current={current!r} locked={GOLDEN_HASH_CONSTANT!r}"
    )
