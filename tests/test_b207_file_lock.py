"""B-207 (part 2b): one exclusive file lock for every state file.

The lock was copied into the assumption WAL, the suite chain, the workspace
digest chain, the manifest ledger and the run marker. ``ract.file_lock`` is
now the one copy: a second holder gets the caller's own error after the
tries, a released lock is taken at once, and a release of a lock that is
not held is reported, never raised.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ract import file_lock
from ract.core.assumptions_wal import WalLockContended
from ract.core.assumptions_wal import _lock_exclusive as wal_lock
from ract.core.assumptions_wal import _unlock as wal_unlock
from ract.core.suite_chain import SuiteChainLockContended
from ract.core.suite_chain import _lock_exclusive as chain_lock
from ract.core.suite_chain import _unlock as chain_unlock


class _Held(Exception):
    pass


def _two(path: Path) -> tuple[int, int]:
    return (
        os.open(path, os.O_RDWR | os.O_CREAT, 0o644),
        os.open(path, os.O_RDWR | os.O_CREAT, 0o644),
    )


def test_a_second_holder_gets_the_callers_error_after_the_tries(tmp_path: Path) -> None:
    first, second = _two(tmp_path / "state.lock")
    tries: list[int] = []

    def contended(n: int) -> Exception:
        tries.append(n)
        return _Held(f"held after {n}")

    try:
        file_lock.lock_exclusive(first, contended=contended)
        with pytest.raises(_Held, match="held after 4"):
            file_lock.lock_exclusive(second, contended=contended, retries=4, backoff_s=0)
        assert tries == [4]
        file_lock.unlock(first)
        file_lock.lock_exclusive(second, contended=contended, retries=1)  # free: at once
        file_lock.unlock(second)
    finally:
        os.close(first)
        os.close(second)


def test_the_position_in_the_file_is_kept(tmp_path: Path) -> None:
    fd = os.open(tmp_path / "state.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        os.write(fd, b"abcdef")
        file_lock.lock_exclusive(fd, contended=_Held)
        assert os.lseek(fd, 0, os.SEEK_CUR) == 6
        file_lock.unlock(fd)
        assert os.lseek(fd, 0, os.SEEK_CUR) == 6
    finally:
        os.close(fd)


def test_releasing_a_lock_not_held_is_reported_not_raised(tmp_path: Path) -> None:
    fd = os.open(tmp_path / "state.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        file_lock.unlock(fd, what="the test file")  # no exception on any system
    finally:
        os.close(fd)


@pytest.mark.parametrize(
    ("lock", "unlock", "error", "name"),
    [
        (wal_lock, wal_unlock, WalLockContended, "assumptions.wal"),
        (chain_lock, chain_unlock, SuiteChainLockContended, "suite_chain.jsonl"),
    ],
)
def test_each_state_file_keeps_its_own_error(tmp_path, lock, unlock, error, name) -> None:  # type: ignore[no-untyped-def]
    first, second = _two(tmp_path / "state.lock")
    try:
        lock(first)
        held = f"{name} is locked by another RACT process; gave up after 3"
        with pytest.raises(error, match=held):
            lock(second)
        unlock(first)
        lock(second)
        unlock(second)
    finally:
        os.close(first)
        os.close(second)


def test_the_run_marker_lock_uses_the_one_helper(tmp_path: Path) -> None:
    from ract.loop_controller import LoopController

    first, second = _two(tmp_path / "run_id.txt.lock")
    try:
        LoopController._acquire_marker_lock(first)
        with pytest.raises(TimeoutError, match="held by another process"):
            LoopController._acquire_marker_lock(second)
        LoopController._release_marker_lock(first)
        LoopController._acquire_marker_lock(second)
        LoopController._release_marker_lock(second)
    finally:
        os.close(first)
        os.close(second)
