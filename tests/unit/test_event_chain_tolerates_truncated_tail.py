"""Regression: :class:`ract.trace.writer.EventReader.load` tolerates a
truncated tail line with a WARN, matching the WAL / manifest_ledger /
workspace-digest / suite-chain tolerant idiom.

v0.5.1 module_09 (Lens F H2 closure). Prior behavior raised
:class:`ChainBrokenError` on any tail parse error, making the event
log the ONLY ledger in the repo whose crash-recovery posture rejected
the on-disk state instead of degrading gracefully. That inversion --
the event log has the strongest cryptographic chain yet the weakest
crash-recovery posture -- was likely accidental.

The alignment WARN-logs the dropped tail line and returns the events
up to the last well-formed line; middle-line JSON errors still raise
:class:`ChainBrokenError` (non-append corruption is a hard failure).

Reference:
- ``_BUILD/audit_2026-08-21/lens_F_trace_events_ledgers.md`` H2.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_09.md``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ract.trace.events import ChainBrokenError
from ract.trace.writer import EventReader, JsonlEventWriter


_RUN_ID = bytes.fromhex("22" * 16)


def _write_five(path: Path) -> list[bytes]:
    writer = JsonlEventWriter(path, run_id=_RUN_ID)
    hashes: list[bytes] = []
    for i in range(5):
        event = writer.emit("run.started", {"iteration": i})
        hashes.append(event.hash)
    writer.close()
    return hashes


def test_truncated_tail_is_warned_and_dropped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A SIGKILL mid-write leaves the last line truncated. Loading the
    file must WARN, drop the tail, and return the first four events.
    """
    events_path = tmp_path / "events.jsonl"
    hashes = _write_five(events_path)
    assert len(hashes) == 5

    # Truncate the last line mid-way so json.loads raises.
    raw = events_path.read_bytes()
    lines = raw.split(b"\n")
    # lines: [line0, line1, ..., line4, b""] due to trailing "\n"
    # Truncate line4 to the first 30 bytes -- an incomplete JSON
    # object that json.loads will refuse.
    lines[-2] = lines[-2][:30]
    events_path.write_bytes(b"\n".join(lines))

    caplog.set_level(logging.WARNING, logger="ract.trace.writer")
    chain = EventReader.load(events_path)
    # Four events (the un-truncated head) survive; the fifth is dropped.
    assert len(chain.events) == 4
    assert chain.events[-1].hash == hashes[3]
    # WARN must have fired.
    assert any(
        "tail line" in record.message.lower() and "dropped" in record.message.lower()
        for record in caplog.records
    ), "tail-tolerance WARN not emitted"


def test_middle_corruption_still_raises(tmp_path: Path) -> None:
    """A malformed MIDDLE line is not the crash-recovery surface --
    it indicates real corruption/tamper and must raise.
    """
    events_path = tmp_path / "events.jsonl"
    _write_five(events_path)
    raw = events_path.read_bytes()
    lines = raw.split(b"\n")
    # Corrupt line 2 (a middle line, not the last).
    lines[2] = b"{not valid json"
    events_path.write_bytes(b"\n".join(lines))

    with pytest.raises(ChainBrokenError):
        EventReader.load(events_path)


def test_writer_reopens_after_torn_tail_and_appends_from_prior_hash(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The full recovery loop: write 5, torn-write truncates the tail,
    reopen the writer, verify the tip is seeded from event 4's hash,
    then append -- the resulting log is a clean 4 + N chain that
    ``EventReader.load`` accepts.
    """
    events_path = tmp_path / "events.jsonl"
    hashes = _write_five(events_path)
    raw = events_path.read_bytes()
    lines = raw.split(b"\n")
    # Truncate line 4 to make it unparseable.
    lines[-2] = lines[-2][:20]
    events_path.write_bytes(b"\n".join(lines))

    caplog.set_level(logging.WARNING, logger="ract.trace.writer")
    reopened = JsonlEventWriter(events_path, run_id=_RUN_ID)
    # Tip must be seeded from event-3's hash (fourth event) because
    # event-4 (fifth) is now torn.
    assert reopened.chain.tip_hash == hashes[3]

    # Append a fresh event -- prev_hash must link cleanly to event-3.
    fresh = reopened.emit("step.started", {"note": "post-truncation"})
    assert fresh.prev_hash == hashes[3]
