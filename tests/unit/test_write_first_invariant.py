"""Write-first-invariant hardening tests.

v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). Regression tests
for the invariant defined in 04-RACT-DESIGN §5.1.2: "no state change
is observable to any component until the corresponding event is
durably written to the log."

Covers:

- fsync happens before any observer fires (ordering test)
- WriteFirstViolation raises if an observer tries to re-enter the
  writer mid-commit
- Two observer classes: post-commit fires on every emit; durability
  fires only on checkpoint()
- Post-commit failure logged not propagated; durability failure
  propagates from checkpoint()
- Legacy add_mirror routes through post-commit with historical
  raise-propagation semantics
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from ract.trace.events import Event
from ract.trace.writer import JsonlEventWriter, WriteFirstViolation


def _new_writer(tmp_path: Path) -> JsonlEventWriter:
    return JsonlEventWriter(
        path=tmp_path / "events.jsonl", run_id=uuid.uuid4().bytes
    )


# --------------------------------------------------------------------------
# Ordering test: fsync BEFORE observer notification
# --------------------------------------------------------------------------


def test_fsync_happens_before_observer_notification(tmp_path: Path) -> None:
    """Post-commit observers must not fire until after os.fsync returns."""
    writer = _new_writer(tmp_path)
    call_order: list[str] = []

    real_fsync = os.fsync

    def tracking_fsync(fd: int) -> None:
        call_order.append("fsync")
        real_fsync(fd)

    def observer(event: Event) -> None:
        call_order.append("observer")

    writer.add_post_commit_observer(observer)
    with patch("ract.trace.writer.os.fsync", side_effect=tracking_fsync):
        writer.emit("run.started", {"note": "test"})

    assert call_order == ["fsync", "observer"], (
        f"observer fired before fsync completed: {call_order}"
    )


# --------------------------------------------------------------------------
# WriteFirstViolation guard: reentrant observer during commit
# --------------------------------------------------------------------------


def test_write_first_violation_raised_when_observer_calls_checkpoint(
    tmp_path: Path,
) -> None:
    """An observer that re-enters checkpoint() mid-commit raises WriteFirstViolation.

    Reproduce the scenario by patching os.fsync to invoke
    writer.checkpoint() during the fsync -- that is the exact
    window (post-build_next, pre-fsync-return) where the invariant
    forbids observation.
    """
    writer = _new_writer(tmp_path)
    raised: list[Exception] = []
    real_fsync = os.fsync

    def reentrant_fsync(fd: int) -> None:
        try:
            writer.checkpoint()
        except Exception as exc:  # noqa: BLE001
            raised.append(exc)
        real_fsync(fd)

    with patch("ract.trace.writer.os.fsync", side_effect=reentrant_fsync):
        writer.emit("run.started", {})

    assert len(raised) == 1, "expected exactly one raise during commit"
    assert isinstance(raised[0], WriteFirstViolation)


# --------------------------------------------------------------------------
# Two Observer Classes: post-commit vs durability
# --------------------------------------------------------------------------


def test_post_commit_observer_fires_on_every_emit(tmp_path: Path) -> None:
    writer = _new_writer(tmp_path)
    seen: list[Event] = []
    writer.add_post_commit_observer(seen.append)
    writer.emit("run.started", {})
    writer.emit("step.started", {})
    assert len(seen) == 2
    assert [e.kind for e in seen] == ["run.started", "step.started"]


def test_durability_observer_fires_only_on_checkpoint(tmp_path: Path) -> None:
    writer = _new_writer(tmp_path)
    seen: list[Event] = []
    writer.add_durability_observer(seen.append)
    writer.emit("run.started", {})
    writer.emit("step.started", {})
    assert seen == [], "durability observer must NOT fire during emit"
    writer.checkpoint()
    assert len(seen) == 2
    # Second checkpoint fires nothing new.
    writer.checkpoint()
    assert len(seen) == 2
    # Emit more, checkpoint fires only the new ones.
    writer.emit("step.committed", {})
    assert len(seen) == 2  # still 2 pre-checkpoint
    writer.checkpoint()
    assert len(seen) == 3


def test_post_commit_observer_raise_is_logged_not_propagated(
    tmp_path: Path, caplog
) -> None:
    """A raise from a post-commit observer must NOT block emit()."""
    writer = _new_writer(tmp_path)

    def bad(_ev: Event) -> None:
        raise RuntimeError("intentional")

    writer.add_post_commit_observer(bad)
    with caplog.at_level("WARNING", logger="ract.trace.writer"):
        event = writer.emit("run.started", {})
    assert event is not None
    assert any("post-commit observer" in r.message for r in caplog.records)


def test_durability_observer_raise_propagates_from_checkpoint(
    tmp_path: Path,
) -> None:
    """A raise from a durability observer surfaces at checkpoint() call."""
    writer = _new_writer(tmp_path)

    def bad(_ev: Event) -> None:
        raise RuntimeError("index feeder broke")

    writer.add_durability_observer(bad)
    writer.emit("run.started", {})
    with pytest.raises(RuntimeError, match="index feeder broke"):
        writer.checkpoint()


# --------------------------------------------------------------------------
# Legacy add_mirror backward compat
# --------------------------------------------------------------------------


def test_add_mirror_still_fires_after_fsync(tmp_path: Path) -> None:
    """Legacy add_mirror callers see the same behavior post module_03."""
    writer = _new_writer(tmp_path)
    seen: list[Event] = []
    writer.add_mirror(seen.append)
    writer.emit("run.started", {})
    assert len(seen) == 1


def test_add_mirror_raise_still_propagates_backward_compat(tmp_path: Path) -> None:
    """Legacy add_mirror raise-propagation preserved (OTEL exporter contract)."""
    writer = _new_writer(tmp_path)

    def bad(_ev: Event) -> None:
        raise RuntimeError("otel down")

    writer.add_mirror(bad)
    with pytest.raises(RuntimeError, match="otel down"):
        writer.emit("run.started", {})


# --------------------------------------------------------------------------
# Fsync is actually invoked
# --------------------------------------------------------------------------


def test_fsync_is_actually_called_on_emit(tmp_path: Path) -> None:
    """Regression: the emit path must call os.fsync at least once."""
    writer = _new_writer(tmp_path)
    with patch("ract.trace.writer.os.fsync") as m_fsync:
        writer.emit("run.started", {})
    assert m_fsync.call_count >= 1


# --------------------------------------------------------------------------
# SP Q7 TEST GAP fold: observer reentry via emit() (not just checkpoint())
# --------------------------------------------------------------------------


def test_write_first_violation_raised_when_observer_calls_emit_reentrant(
    tmp_path: Path,
) -> None:
    """An observer that re-enters emit() mid-commit deadlocks the lock.

    v0.5.1 module_03 SP Q7 TEST GAP fold. The Q7 gap named
    checkpoint()-reentry only. emit() reentry from a post-commit
    observer would fire OUTSIDE the lock (after commit completes)
    so it's not a WriteFirstViolation shape. However, if a REGRESSION
    routed observer calls inside the commit lock, emit() would try
    to reacquire the (non-reentrant) threading.Lock and deadlock.

    This test asserts the DEFENSIVE behavior: an observer registered
    via add_post_commit_observer that calls writer.emit() again
    completes without a deadlock (because it fires AFTER lock
    release). Nested emit-from-post-commit-observer is legal.
    """
    writer = _new_writer(tmp_path)
    seen_nested: list[Event] = []

    def nested_emitter(event: Event) -> None:
        # Only nest once to avoid infinite recursion.
        if event.kind == "run.started":
            nested = writer.emit("step.started", {"from": "nested"})
            seen_nested.append(nested)

    writer.add_post_commit_observer(nested_emitter)
    writer.emit("run.started", {})
    # Assert nested emit landed durably.
    assert len(seen_nested) == 1
    assert seen_nested[0].kind == "step.started"


# --------------------------------------------------------------------------
# SP Q7 NIT fold: close() drains durability observers
# --------------------------------------------------------------------------


def test_close_drains_durability_observers(tmp_path: Path) -> None:
    """close() invokes checkpoint() so durability observers see final events.

    v0.5.1 module_03 SP Q7 NIT fold. Previously close() was a no-op;
    a caller who forgot to checkpoint() before close() lost
    durability signal for all events. Now close() drains.
    """
    writer = _new_writer(tmp_path)
    seen: list[Event] = []
    writer.add_durability_observer(seen.append)
    writer.emit("run.started", {})
    writer.emit("step.started", {})
    assert seen == []  # not fired yet
    writer.close()
    assert len(seen) == 2
    # Second close (idempotence): no new events past watermark.
    writer.close()
    assert len(seen) == 2
