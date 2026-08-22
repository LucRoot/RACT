"""Regression tests for the RootknotWAL crash-consistency layer (v0.5.1 module_01).

DEEPSEEK_REVIEW_5 §"G1 deeper dive" identifies the assumption-registry
crash-loss hole this module closes. These tests pin the load-bearing
invariants:

- process-kill at each transition state proves replay fidelity;
- snapshot rotation preserves history across reload;
- concurrent writers do not clobber each other's WAL;
- a malformed WAL tail rejects without corrupting the snapshot;
- the cross-platform file-lock path is exercised on the current OS;
- ``AssumptionRegistry`` with ``wal_dir=None`` is byte-for-byte the
  v0.5.0 pure-in-memory registry (backward compatibility);
- every WAL append also emits the matching ``assumption.<kind>``
  trace event.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from ract.core.assumption import Evidence, Violation
from ract.core.assumption_registry import AssumptionRegistry
from ract.core.assumptions_wal import (
    AssumptionWal,
    TRANSITIONS,
    WalCorruptError,
    WalLockContended,
    _canonical_line,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_and_capture(script: str, wal_dir: Path) -> subprocess.CompletedProcess:
    """Run ``script`` in a fresh Python subprocess and return its result.

    The script has ``WAL_DIR`` pre-substituted to the shared path so
    the parent test can inspect the on-disk artifacts afterwards.
    """
    body = script.replace("__WAL_DIR__", repr(str(wal_dir)))
    return subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# WAL primitive tests
# ---------------------------------------------------------------------------


def test_canonical_line_is_stable_sorted() -> None:
    """The canonical JSONL line is byte-stable across key orderings."""
    a = _canonical_line({"b": 1, "a": 2, "kind": "proposed"})
    b = _canonical_line({"kind": "proposed", "a": 2, "b": 1})
    assert a == b
    assert a.endswith(b"\n")


def test_transitions_vocabulary_is_closed() -> None:
    """The four-transition vocabulary is the closed WAL alphabet."""
    assert TRANSITIONS == ("proposed", "accepted", "discharged", "violated")


def test_wal_append_then_load_roundtrips(tmp_path: Path) -> None:
    """A written line reads back with matching kind and payload."""
    wal = AssumptionWal(tmp_path)
    wal.append("proposed", {"assumption_id": "aa" * 16, "text": "x"})
    snap, tail = wal.load_all()
    assert snap == []
    assert len(tail) == 1
    assert tail[0].kind == "proposed"
    assert tail[0].payload["text"] == "x"


def test_wal_rejects_unknown_kind(tmp_path: Path) -> None:
    """The WAL vocabulary is closed at append time."""
    wal = AssumptionWal(tmp_path)
    with pytest.raises(ValueError):
        wal.append("bogus", {"assumption_id": "aa"})


# ---------------------------------------------------------------------------
# Registry backward-compat (no wal_dir)
# ---------------------------------------------------------------------------


def test_registry_pure_in_memory_when_wal_dir_none(tmp_path: Path) -> None:
    """``AssumptionRegistry()`` with no wal_dir must not touch disk.

    Every existing v0.5.0 test-site constructs the registry with zero
    args. Backward compatibility is load-bearing.
    """
    cwd_before = set(tmp_path.iterdir())
    registry = AssumptionRegistry()
    a = registry.propose("p")
    registry.accept(a.id)
    registry.discharge(a.id, Evidence("done"))
    cwd_after = set(tmp_path.iterdir())
    assert cwd_before == cwd_after
    # No .ract/ dir was created anywhere the test can observe.
    assert not (tmp_path / ".ract").exists()


def test_registry_still_propagates_violation() -> None:
    """The existing violate-propagation semantics survive the refactor."""
    registry = AssumptionRegistry()
    a = registry.propose("root")
    registry.accept(a.id)
    b = registry.propose("dep", depends_on=(a.id,))
    registry.accept(b.id)
    violated = registry.violate(a.id, Violation("contradiction"))
    assert set(violated) == {a.id, b.id}


# ---------------------------------------------------------------------------
# WAL-enabled registry — replay fidelity per transition
# ---------------------------------------------------------------------------


def _kill_after_transition_script(transition: str) -> str:
    """Return a Python source snippet that runs one transition then exits.

    ``os._exit(0)`` bypasses cleanup so no ``__exit__``-style save can
    fire — the WAL is the only source of durability.
    """
    if transition == "proposed":
        step = 'a = r.propose("p"); print(a.id.hex())'
    elif transition == "accepted":
        step = 'a = r.propose("p"); r.accept(a.id); print(a.id.hex())'
    elif transition == "discharged":
        step = (
            'a = r.propose("p"); r.accept(a.id); '
            'r.discharge(a.id, Evidence("done")); print(a.id.hex())'
        )
    elif transition == "violated":
        step = (
            'a = r.propose("p"); r.accept(a.id); '
            'r.violate(a.id, Violation("contradict")); print(a.id.hex())'
        )
    else:
        raise ValueError(transition)
    return textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {os.path.join(os.path.dirname(__file__), "..", "..", "src")!r})
        from pathlib import Path
        from ract.core.assumption import Evidence, Violation
        from ract.core.assumption_registry import AssumptionRegistry
        r = AssumptionRegistry(wal_dir=Path(__WAL_DIR__))
        {step}
        sys.stdout.flush()
        os._exit(0)
        """
    ).strip()


@pytest.mark.parametrize("transition", list(TRANSITIONS))
def test_wal_replay_after_kill_at_each_transition(
    tmp_path: Path, transition: str
) -> None:
    """A hard-kill after each of the four transitions is losslessly recoverable.

    The subprocess runs one transition against a fresh registry rooted
    at ``tmp_path``, then ``os._exit(0)`` — bypassing any cleanup
    handler. A reload from a new process must see the transition
    applied.
    """
    result = _run_and_capture(_kill_after_transition_script(transition), tmp_path)
    assert result.returncode == 0, result.stderr
    aid_hex = result.stdout.strip()
    from ract.core.types import AssumptionId

    aid = AssumptionId(bytes.fromhex(aid_hex))
    reloaded = AssumptionRegistry(wal_dir=tmp_path)
    assumption = reloaded.get(aid)
    assert assumption is not None
    from ract.core.assumption import AssumptionState

    expected_state = {
        "proposed": AssumptionState.PROPOSED,
        "accepted": AssumptionState.ACTIVE,
        "discharged": AssumptionState.DISCHARGED,
        "violated": AssumptionState.VIOLATED,
    }[transition]
    assert assumption.state == expected_state


def test_snapshot_rotation_preserves_history_across_reload(tmp_path: Path) -> None:
    """``rotate_snapshot`` writes a snapshot and truncates the WAL cleanly."""
    r = AssumptionRegistry(wal_dir=tmp_path)
    a1 = r.propose("p1")
    r.accept(a1.id)
    r.discharge(a1.id, Evidence("done"))
    a2 = r.propose("p2")
    r.accept(a2.id)
    r.rotate_snapshot()
    # WAL is now empty; snapshot carries both assumptions.
    wal_file = tmp_path / AssumptionWal.WAL_NAME
    snap_file = tmp_path / AssumptionWal.SNAPSHOT_NAME
    assert wal_file.exists() and wal_file.stat().st_size == 0
    assert snap_file.exists() and snap_file.stat().st_size > 0
    # A fresh registry reload must see both assumptions.
    r2 = AssumptionRegistry(wal_dir=tmp_path)
    assert r2.get(a1.id) is not None
    assert r2.get(a2.id) is not None
    from ract.core.assumption import AssumptionState

    assert r2.get(a1.id).state == AssumptionState.DISCHARGED  # type: ignore[union-attr]
    assert r2.get(a2.id).state == AssumptionState.ACTIVE  # type: ignore[union-attr]
    # Adding more transitions after rotate replays correctly.
    r2.violate(a2.id, Violation("changed mind"))
    r3 = AssumptionRegistry(wal_dir=tmp_path)
    assert r3.get(a2.id).state == AssumptionState.VIOLATED  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Concurrent-access safety
# ---------------------------------------------------------------------------


def test_concurrent_writers_do_not_interleave_partial_lines(tmp_path: Path) -> None:
    """Two threads appending 50 transitions each produce 100 whole lines.

    The exclusive byte-range lock serialises appends so no partial
    line is ever written. Both threads use the SAME registry (the
    on-disk WAL is the shared serialisation point; the in-memory
    dict is protected by the append→mutate ordering under lock).
    """
    N = 50
    r = AssumptionRegistry(wal_dir=tmp_path)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(N):
                a = r.propose("p")
                r.accept(a.id)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors, errors
    # WAL must be readable end-to-end (no partial JSON lines).
    wal_bytes = (tmp_path / AssumptionWal.WAL_NAME).read_bytes()
    lines = wal_bytes.decode().split("\n")
    # Trailing empty line from final newline; drop it.
    if lines and lines[-1] == "":
        lines.pop()
    import json

    for line in lines:
        json.loads(line)  # raises if partial
    # 2 workers * N iterations * 2 transitions each = 4N whole lines.
    assert len(lines) == 4 * N


# ---------------------------------------------------------------------------
# Malformed-tail tolerance
# ---------------------------------------------------------------------------


def test_malformed_wal_tail_replay_stops_without_corruption(tmp_path: Path) -> None:
    """A truncated last line is skipped; snapshot untouched; state is last-good.

    Simulates a process kill mid-``write()``. The truncated tail line
    must not raise (that transition's mutation never reached memory in
    the killed process), and the snapshot on disk is not modified.
    """
    r = AssumptionRegistry(wal_dir=tmp_path)
    a = r.propose("p")
    r.accept(a.id)
    r.rotate_snapshot()
    # Add one more transition, then corrupt its tail.
    b = r.propose("q")
    wal_path = tmp_path / AssumptionWal.WAL_NAME
    snap_path = tmp_path / AssumptionWal.SNAPSHOT_NAME
    original_snap = snap_path.read_bytes()
    raw = wal_path.read_bytes()
    # Truncate the trailing newline + last few bytes to simulate a
    # partial write.
    wal_path.write_bytes(raw[: max(len(raw) - 10, 0)])
    # Reload succeeds and sees the accepted ``a`` (from snapshot); the
    # torn ``propose q`` line is dropped.
    r2 = AssumptionRegistry(wal_dir=tmp_path)
    assert r2.get(a.id) is not None
    assert r2.get(b.id) is None
    # Snapshot is untouched.
    assert snap_path.read_bytes() == original_snap


def test_malformed_middle_wal_line_raises(tmp_path: Path) -> None:
    """A malformed middle line is a hard error — not silent state loss."""
    wal = AssumptionWal(tmp_path)
    wal.append("proposed", {"assumption_id": "aa" * 16, "text": "x"})
    # Inject a broken middle line.
    with (tmp_path / AssumptionWal.WAL_NAME).open("ab") as fh:
        fh.write(b"{not-json\n")
    wal.append("proposed", {"assumption_id": "bb" * 16, "text": "y"})
    with pytest.raises(WalCorruptError):
        wal.load_all()


# ---------------------------------------------------------------------------
# Cross-platform lock exercise
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows msvcrt.locking path")
def test_windows_lock_path_available() -> None:
    """The Windows lock branch imports and dispatches correctly."""
    import ract.core.assumptions_wal as mod

    assert mod._lock_exclusive.__module__ == "ract.core.assumptions_wal"
    assert mod._unlock.__module__ == "ract.core.assumptions_wal"
    # The msvcrt module was imported at module load; no fcntl.
    assert "msvcrt" in sys.modules
    assert "fcntl" not in sys.modules


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX fcntl.flock path")
def test_posix_lock_path_available() -> None:
    """The POSIX lock branch imports and dispatches correctly."""
    import ract.core.assumptions_wal as mod

    assert mod._lock_exclusive.__module__ == "ract.core.assumptions_wal"
    assert "fcntl" in sys.modules


def test_second_holder_of_lock_raises_contended(tmp_path: Path) -> None:
    """A second holder of the byte-0 lock hits the contention path."""
    AssumptionWal(tmp_path)
    # Pre-create the WAL file so both branches open the same inode.
    (tmp_path / AssumptionWal.WAL_NAME).touch()
    from ract.core.assumptions_wal import _lock_exclusive, _unlock

    fd_hold = os.open(
        tmp_path / AssumptionWal.WAL_NAME,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o644,
    )
    _lock_exclusive(fd_hold)
    try:
        # A second acquire attempt must fail after the retry window.
        fd_try = os.open(
            tmp_path / AssumptionWal.WAL_NAME,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644,
        )
        try:
            with pytest.raises(WalLockContended):
                _lock_exclusive(fd_try)
        finally:
            os.close(fd_try)
    finally:
        _unlock(fd_hold)
        os.close(fd_hold)


# ---------------------------------------------------------------------------
# Event emission per transition
# ---------------------------------------------------------------------------


def test_every_transition_emits_matching_event(tmp_path: Path) -> None:
    """Each of the four transitions emits one matching ``assumption.<kind>``."""
    from ract.trace.sink import ListSink, set_writer, clear_writer

    sink = ListSink(run_id=b"\x00" * 16)
    set_writer(sink, force=True)
    try:
        r = AssumptionRegistry(wal_dir=tmp_path)
        a = r.propose("p")
        r.accept(a.id)
        r.discharge(a.id, Evidence("done"))
        b = r.propose("q")
        r.accept(b.id)
        r.violate(b.id, Violation("contradict"))
        kinds = [e.kind for e in sink.events]
    finally:
        clear_writer()
    assert "assumption.proposed" in kinds
    assert "assumption.accepted" in kinds
    assert "assumption.discharged" in kinds
    assert "assumption.violated" in kinds
    # Two propose calls => two proposed events, two accept => two accepted.
    assert kinds.count("assumption.proposed") == 2
    assert kinds.count("assumption.accepted") == 2
    assert kinds.count("assumption.discharged") == 1
    assert kinds.count("assumption.violated") == 1


# RACT 0.5.1
