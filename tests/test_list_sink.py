"""Tests for the in-memory ListSink writer."""

from __future__ import annotations

import os

import pytest

from ract.trace.events import ChainBrokenError
from ract.trace.sink import ListSink


def _run_id() -> bytes:
    return os.urandom(16)


def test_list_sink_records_events() -> None:
    """Emitting N events appends them to ``events`` in order."""
    sink = ListSink(run_id=_run_id())
    sink.emit("run.started", {"a": 1})
    sink.emit("step.started", {"a": 2})
    sink.emit("step.committed", {"a": 3})

    assert len(sink.events) == 3
    assert [e.kind for e in sink.events] == [
        "run.started",
        "step.started",
        "step.committed",
    ]
    payloads = [e.payload for e in sink.events]
    assert payloads == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_list_sink_hash_chain_verified() -> None:
    """The chain links across in-memory events; tamper raises ChainBrokenError."""
    sink = ListSink(run_id=_run_id())
    sink.emit("run.started", {"k": "v"})
    sink.emit("step.started", {"k": "v"})
    sink.emit("step.committed", {"k": "v"})

    # Every event's prev_hash matches the prior event's hash.
    prior_hash = b"\x00" * 32
    for event in sink.events:
        assert event.prev_hash == prior_hash
        prior_hash = event.hash

    # A separate ListSink cannot append a tampered event with a stale
    # prev_hash without ``ChainBrokenError`` firing (rebuild through
    # EventChain.append which is what emit() uses internally).
    from ract.trace.events import EventChain, hash_event, new_event_id

    original_events = list(sink.events)
    replay = EventChain(run_id=sink.run_id)
    for event in original_events:
        replay.append(event)

    # Now hand-craft a bad event that claims a wrong prev_hash and try
    # to append. It must be refused.
    bad = original_events[-1]
    forged = type(bad)(
        id=new_event_id(),
        run_id=bad.run_id,
        step_id=bad.step_id,
        parent_id=bad.parent_id,
        timestamp_ns=bad.timestamp_ns + 1,
        kind="step.committed",
        payload={"tampered": True},
        hash=hash_event(
            kind="step.committed",
            payload={"tampered": True},
            prev_hash=b"\x00" * 32,  # wrong tip
            id_bytes=new_event_id(),
            run_id=bad.run_id,
            step_id=bad.step_id,
            parent_id=bad.parent_id,
            timestamp_ns=bad.timestamp_ns + 1,
        ),
        prev_hash=b"\x00" * 32,
    )
    with pytest.raises(ChainBrokenError):
        replay.append(forged)


# RACT 0.4.1
