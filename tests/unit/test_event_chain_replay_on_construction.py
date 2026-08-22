"""Regression: :class:`ract.trace.writer.JsonlEventWriter` must reseed
its :class:`EventChain.tip_hash` from the on-disk tail when a writer
is constructed against a file that already carries events.

v0.5.1 module_09 (Lens F H1 closure). The prior __init__ set
``self.chain = EventChain(run_id=run_id)`` unconditionally, whose
default ``tip_hash`` is the 32-zero-byte GENESIS. A second writer
opened on the same file (crash-restart, a repair tool that appends,
a second loop under the same run_id) then wrote a first event whose
``prev_hash = 0*32``. The chain was silently broken; only the next
``EventReader.load`` call raised.

The fix walks the on-disk tail (last line first) and seeds
``tip_hash`` from the first parseable event's ``hash`` field, so a
newly constructed writer picks up exactly where the last one left off.

Reference:
- ``_BUILD/audit_2026-08-21/lens_F_trace_events_ledgers.md`` H1.
- ``_BUILD/ract_v0.5.1_wiring_completion/module_09.md``.
"""

from __future__ import annotations

from pathlib import Path

from ract.runtime import bind_run_id
from ract.trace.events import _GENESIS_HASH
from ract.trace.writer import EventReader, JsonlEventWriter


_RUN_ID = bytes.fromhex("11" * 16)


def _write_five(path: Path) -> bytes:
    """Write five events; return the fifth event's hash."""
    writer = JsonlEventWriter(path, run_id=_RUN_ID)
    last_hash: bytes = b""
    for i in range(5):
        event = writer.emit(
            "run.started",
            {"iteration": i, "note": f"event-{i}"},
        )
        last_hash = event.hash
    writer.close()
    return last_hash


def test_reopen_seeds_tip_from_disk_tail(tmp_path: Path) -> None:
    """After a first writer emits 5 events + closes, a second writer
    opened on the same path must seed its ``tip_hash`` from the fifth
    event's hash so the next append's ``prev_hash`` links cleanly.
    """
    events_path = tmp_path / "events.jsonl"
    fifth_hash = _write_five(events_path)
    assert events_path.is_file()

    reopened = JsonlEventWriter(events_path, run_id=_RUN_ID)
    # After reseed the writer's tip_hash MUST equal the fifth event's
    # hash -- not the GENESIS default.
    assert reopened.chain.tip_hash != _GENESIS_HASH
    assert reopened.chain.tip_hash == fifth_hash

    # The next append's prev_hash must reference the fifth event's
    # hash. If the reseed had defaulted to GENESIS the append would
    # write ``prev_hash = 0*32`` and later EventReader.load would
    # raise ChainBrokenError.
    sixth = reopened.emit("step.started", {"step": "post-reopen"})
    assert sixth.prev_hash == fifth_hash

    # Full-chain verify: the entire log (5 pre + 1 post) must load
    # without ChainBrokenError.
    chain = EventReader.load(events_path)
    assert len(chain.events) == 6
    assert chain.events[-1].hash == sixth.hash


def test_reopen_on_empty_file_stays_at_genesis(tmp_path: Path) -> None:
    """A writer opened against a zero-byte file uses GENESIS -- the
    file exists but carries no events, so GENESIS is the correct tip.
    """
    events_path = tmp_path / "events.jsonl"
    events_path.touch()  # zero-byte
    writer = JsonlEventWriter(events_path, run_id=_RUN_ID)
    assert writer.chain.tip_hash == _GENESIS_HASH
    first = writer.emit("run.started", {"iteration": 0})
    assert first.prev_hash == _GENESIS_HASH


def test_reopen_ignores_missing_file(tmp_path: Path) -> None:
    """A writer opened against a nonexistent file uses GENESIS."""
    events_path = tmp_path / "no_such_file.jsonl"
    assert not events_path.exists()
    writer = JsonlEventWriter(events_path, run_id=_RUN_ID)
    assert writer.chain.tip_hash == _GENESIS_HASH


def test_reopen_on_invalid_utf8_refuses_construction(tmp_path: Path) -> None:
    """SP Q6 [DEFECT] amendment: a UTF-8 decode failure on the
    events.jsonl file MUST raise :class:`ChainBrokenError`, not
    silently fall through to a GENESIS reseed. Falling through would
    let the writer append a first event with ``prev_hash = 0*32``
    while the file already carries hex-encoded events whose tail hash
    disagrees -- the chain would silently break on the next full-file
    verify.
    """
    from ract.trace.events import ChainBrokenError

    events_path = tmp_path / "events.jsonl"
    events_path.write_bytes(b"\xff\xfe\x00\x00 not valid UTF-8 \x80\x81\n")
    import pytest as _pytest

    with _pytest.raises(ChainBrokenError):
        JsonlEventWriter(events_path, run_id=_RUN_ID)


def test_reopen_uses_ambient_run_id(tmp_path: Path) -> None:
    """The reseed path must work when the writer resolves run_id from
    the ambient binding (module_06 wire-in) rather than an explicit arg.
    """
    events_path = tmp_path / "events.jsonl"
    fifth_hash = _write_five(events_path)

    with bind_run_id(_RUN_ID.hex()):
        reopened = JsonlEventWriter(events_path)
    assert reopened.chain.tip_hash == fifth_hash
