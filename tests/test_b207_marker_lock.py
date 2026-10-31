"""B-207 (part 2a): the run-marker lock never goes on without the lock.

``LoopController._acquire_marker_lock`` tried three times and then returned as
if it held the lock, so two runs could write the run id at once. It now
raises ``TimeoutError`` after its tries, and the caller reads the id the other
process writes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ract.loop_controller import LoopController


def test_a_held_lock_is_reported_not_ignored(tmp_path: Path) -> None:
    lock = tmp_path / "run_id.txt.lock"
    first = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o644)
    second = os.open(lock, os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        LoopController._acquire_marker_lock(first)
        with pytest.raises(TimeoutError, match="held by another process"):
            LoopController._acquire_marker_lock(second)
        LoopController._release_marker_lock(first)
        LoopController._acquire_marker_lock(second)  # free again: taken at once
        LoopController._release_marker_lock(second)
    finally:
        os.close(first)
        os.close(second)
