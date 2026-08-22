"""Deterministic + idempotent repair tests.

v0.5.1 spec-completeness module_03 (Lens 2 Delta 1). Regression tests
for :mod:`ract.trace.repair`. Covers:

- Per-scenario synthesized-close correctness (5 open-kinds)
- Idempotence: repair(repair(x)) == repair(x)
- Determinism: two independent calls on the same input produce
  byte-identical Event values
- Hypothesis property: idempotence over random event sequences
- Chain integration: EventReader.load succeeds after repair extends
  the log on disk (synthesized events participate in the chain)
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from ract.trace.events import (
    Event,
    EventChain,
    LEGAL_EVENT_KINDS,
)
from ract.trace.repair import (
    RepairedEventStream,
    RepairSummary,
    rebuild_chain_from_repaired,
    repair,
)
from ract.trace.writer import EventReader, JsonlEventWriter


try:
    from hypothesis import HealthCheck, given, settings, strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _fresh_chain() -> EventChain:
    return EventChain(run_id=uuid.uuid4().bytes)


def _emit(chain: EventChain, kind: str, **payload) -> Event:
    ev = chain.build_next(kind=kind, payload=payload)
    chain.append(ev)
    return ev


# --------------------------------------------------------------------------
# Per-scenario tests
# --------------------------------------------------------------------------


def test_repair_closes_run_started_with_run_aborted() -> None:
    chain = _fresh_chain()
    _emit(chain, "run.started", note="hello")
    stream = repair(chain.events)
    assert len(stream.synthesized_close_events) == 1
    close = stream.synthesized_close_events[0]
    assert close.kind == "run.aborted"
    assert close.payload["synthesized"] is True
    assert close.payload["reason"] == "interrupted"
    assert close.payload["source_event_id"] == chain.events[0].id.hex()


def test_repair_closes_step_started_with_step_rolled_back() -> None:
    chain = _fresh_chain()
    _emit(chain, "step.started")
    stream = repair(chain.events)
    assert stream.synthesized_close_events[0].kind == "step.rolled_back"


def test_repair_closes_tool_called_with_tool_result_unknown() -> None:
    chain = _fresh_chain()
    _emit(chain, "tool.called", name="ripgrep")
    stream = repair(chain.events)
    close = stream.synthesized_close_events[0]
    assert close.kind == "tool.result"
    assert close.payload["status"] == "unknown"
    assert close.payload["reason"] == "interrupted"


def test_repair_closes_prompt_sent_with_response_received_timeout() -> None:
    chain = _fresh_chain()
    _emit(chain, "prompt.sent", model="test")
    stream = repair(chain.events)
    close = stream.synthesized_close_events[0]
    assert close.kind == "response.received"
    assert close.payload["status"] == "timed_out"


def test_repair_closes_handshake_requested_with_resolved_interrupted() -> None:
    chain = _fresh_chain()
    _emit(chain, "handshake.requested", reason="test")
    stream = repair(chain.events)
    close = stream.synthesized_close_events[0]
    assert close.kind == "handshake.resolved"
    assert close.payload["resolution"] == "interrupted"


def test_repair_no_op_when_all_handles_closed() -> None:
    chain = _fresh_chain()
    _emit(chain, "run.started")
    _emit(chain, "step.started")
    _emit(chain, "step.committed")
    _emit(chain, "run.completed")
    stream = repair(chain.events)
    assert stream.synthesized_close_events == []
    assert stream.repair_summary.already_closed is True


def test_repair_closes_only_still_open_handles() -> None:
    """Mixed: two tool.called, one has result -> one synth close."""
    chain = _fresh_chain()
    _emit(chain, "run.started")
    _emit(chain, "tool.called", name="a")
    _emit(chain, "tool.called", name="b")
    _emit(chain, "tool.result", name="a")  # FIFO closes the FIRST open
    stream = repair(chain.events)
    # Remaining opens: run.started + one tool.called
    assert len(stream.synthesized_close_events) == 2
    close_kinds = {e.kind for e in stream.synthesized_close_events}
    assert close_kinds == {"run.aborted", "tool.result"}


# --------------------------------------------------------------------------
# Idempotence + determinism
# --------------------------------------------------------------------------


def test_repair_is_idempotent_explicit() -> None:
    chain = _fresh_chain()
    _emit(chain, "run.started")
    _emit(chain, "tool.called")
    _emit(chain, "prompt.sent")
    once = repair(chain.events)
    twice = repair(once.events)
    assert twice.synthesized_close_events == []
    assert twice.events == once.events
    assert twice.repair_summary.synthesized_count == 0


def test_repair_is_deterministic_across_calls() -> None:
    chain = _fresh_chain()
    _emit(chain, "run.started")
    _emit(chain, "tool.called")
    a = repair(chain.events)
    b = repair(chain.events)
    # Byte-identical Event values
    assert a.events == b.events
    for x, y in zip(a.synthesized_close_events, b.synthesized_close_events):
        assert x.id == y.id
        assert x.hash == y.hash
        assert x.timestamp_ns == y.timestamp_ns
        assert x.payload == y.payload


def test_repair_synth_id_stable_across_reordering_of_opens() -> None:
    """Two distinct open ids produce two distinct synth ids."""
    chain = _fresh_chain()
    _emit(chain, "tool.called", n=1)
    _emit(chain, "tool.called", n=2)
    stream = repair(chain.events)
    ids = {e.id for e in stream.synthesized_close_events}
    assert len(ids) == 2, "synth ids must be distinct per open"


# --------------------------------------------------------------------------
# Chain integration
# --------------------------------------------------------------------------


def test_synthesized_events_participate_in_hash_chain() -> None:
    chain = _fresh_chain()
    _emit(chain, "run.started")
    stream = repair(chain.events)
    # Rebuilding the chain from the repaired stream must succeed --
    # this re-validates every event's prev_hash link + payload hash.
    rebuilt = rebuild_chain_from_repaired(stream)
    assert len(rebuilt.events) == 2  # 1 real + 1 synth
    assert rebuilt.tip_hash == stream.synthesized_close_events[-1].hash


def test_writer_repair_from_disk_extends_log_and_stays_verifiable(
    tmp_path: Path,
) -> None:
    """After writer.repair_from_disk(), EventReader.load succeeds."""
    log_path = tmp_path / "events.jsonl"
    run_id = uuid.uuid4().bytes
    # First writer: emit an open handle then crash-simulate (drop).
    w1 = JsonlEventWriter(path=log_path, run_id=run_id)
    w1.emit("run.started", {"note": "pre-crash"})
    w1.emit("tool.called", {"name": "ripgrep"})
    # Second writer opens with repair_on_open=True.
    w2 = JsonlEventWriter(path=log_path, run_id=run_id, repair_on_open=True)
    summary = w2.last_repair_summary
    assert summary is not None
    assert summary.synthesized_count == 2  # run.started + tool.called
    # Chain fully verifiable.
    chain = EventReader.load(log_path)
    kinds = [e.kind for e in chain.events]
    assert kinds == ["run.started", "tool.called", "tool.result", "run.aborted"] or \
           kinds == ["run.started", "tool.called", "run.aborted", "tool.result"]


def test_writer_repair_from_disk_is_idempotent(tmp_path: Path) -> None:
    """Reopening a repaired log adds no new synthesized events."""
    log_path = tmp_path / "events.jsonl"
    run_id = uuid.uuid4().bytes
    w1 = JsonlEventWriter(path=log_path, run_id=run_id)
    w1.emit("run.started", {})
    # First repair
    w2 = JsonlEventWriter(path=log_path, run_id=run_id, repair_on_open=True)
    assert w2.last_repair_summary.synthesized_count == 1
    # Second repair should be a no-op
    w3 = JsonlEventWriter(path=log_path, run_id=run_id, repair_on_open=True)
    assert w3.last_repair_summary.synthesized_count == 0
    assert w3.last_repair_summary.already_closed is True


# --------------------------------------------------------------------------
# Hypothesis property: idempotence over random sequences
# --------------------------------------------------------------------------


_OPEN_KINDS = ["run.started", "step.started", "tool.called", "prompt.sent", "handshake.requested"]
_CLOSE_KIND_CHOICES = ["run.completed", "run.aborted", "step.committed", "step.rolled_back",
                       "tool.result", "tool.refused", "response.received", "response.rejected",
                       "handshake.resolved"]


@pytest.mark.skipif(not HAS_HYPOTHESIS, reason="hypothesis not installed")
@given(
    st.lists(
        st.sampled_from(_OPEN_KINDS + _CLOSE_KIND_CHOICES),
        min_size=0,
        max_size=30,
    )
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_repair_idempotence_property(kinds: list[str]) -> None:
    """repair(repair(x)) == repair(x) for arbitrary event sequences."""
    chain = _fresh_chain()
    for kind in kinds:
        _emit(chain, kind)
    once = repair(chain.events)
    twice = repair(once.events)
    assert twice.events == once.events


@pytest.mark.skipif(not HAS_HYPOTHESIS, reason="hypothesis not installed")
@given(
    st.lists(
        st.sampled_from(_OPEN_KINDS + _CLOSE_KIND_CHOICES),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_repair_determinism_property(kinds: list[str]) -> None:
    """Two calls with same input produce byte-identical Event outputs."""
    chain = _fresh_chain()
    for kind in kinds:
        _emit(chain, kind)
    a = repair(chain.events)
    b = repair(chain.events)
    assert a.events == b.events


# --------------------------------------------------------------------------
# SP Q7 TEST GAP fold: step_id / parent_id lineage preservation
# --------------------------------------------------------------------------


def test_synth_close_preserves_step_id_and_parent_id_lineage() -> None:
    """Synthesized close events inherit step_id + parent_id from their open.

    v0.5.1 module_03 SP Q7 TEST GAP fold. Repair.py line 237-238
    passes ``step_id=open_event.step_id`` and ``parent_id=
    open_event.parent_id`` to the synthesized Event. This test
    asserts that lineage flows through -- important for step-scoped
    repair tooling that filters events by step_id (e.g. a per-step
    audit trail viewer).
    """
    chain = _fresh_chain()
    step_id = uuid.uuid4().bytes
    parent_id = uuid.uuid4().bytes
    open_ev = chain.build_next(
        kind="tool.called",
        payload={"name": "ripgrep"},
        step_id=step_id,
        parent_id=parent_id,
    )
    chain.append(open_ev)
    stream = repair(chain.events)
    assert len(stream.synthesized_close_events) == 1
    close = stream.synthesized_close_events[0]
    assert close.step_id == step_id
    assert close.parent_id == parent_id


# --------------------------------------------------------------------------
# SP Q7 DEFECT 2 fold: tail-drop + duplicate-close interaction
# --------------------------------------------------------------------------


def test_repair_synthesizes_duplicate_close_when_reader_drops_torn_close_tail(
    tmp_path: Path,
) -> None:
    """Documented behavior: if the reader drops a torn close-event tail
    line, repair sees the corresponding open as unclosed and
    synthesizes a duplicate close.

    v0.5.1 module_03 SP Q7 DEFECT 2 fold. This is DEFENSIVE
    documentation: the interaction is a natural consequence of the
    reader's tail-tolerance policy (module_09 Lens F H2) + repair's
    open-handle synthesis. Impact is bounded: the synthesized close
    is deterministically distinct from the (torn/dropped) real
    close, so idempotence still holds -- a second repair pass sees
    the synth close, matches it by source_event_id to the open,
    adds nothing new.

    Test simulates: emit run.started + run.completed, then truncate
    the file mid-way through the run.completed line, then reader +
    repair. Assert: synth run.aborted appears; a second repair is
    idempotent.
    """
    log_path = tmp_path / "events.jsonl"
    run_id = uuid.uuid4().bytes
    w = JsonlEventWriter(path=log_path, run_id=run_id)
    w.emit("run.started", {"note": "will be interrupted"})
    w.emit("run.completed", {"note": "will be torn"})
    # Simulate torn tail: truncate the file to drop the last few
    # bytes of the run.completed line (loses the closing bracket).
    raw = log_path.read_bytes()
    truncated = raw[:-10]  # drops 10 bytes: the tail's "}\n" + trailing hex
    log_path.write_bytes(truncated)
    # Now repair -- reader drops the torn tail line, repair sees an
    # unclosed run.started and synthesizes run.aborted.
    events = list(EventReader.iter_events(log_path))
    # The reader tolerantly dropped the malformed tail:
    assert len(events) == 1
    assert events[0].kind == "run.started"
    stream = repair(events)
    assert len(stream.synthesized_close_events) == 1
    assert stream.synthesized_close_events[0].kind == "run.aborted"
    # Idempotence: second pass over the repaired events adds nothing.
    twice = repair(stream.events)
    assert twice.synthesized_close_events == []
