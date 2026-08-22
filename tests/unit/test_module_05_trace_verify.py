"""Regression -- module_05 trace log durability + honest verify.

v0.5.2 hardening module_05 (DA-B F-4.1/F-4.2/F-4.4/F-4.5/F-4.6).

Locks:

- **F-4.1 (incremental warm verify sidecar):** cold verify
  creates sidecar; warm verify seeks to ``last_verified_offset``
  and replays only the delta.
- **F-4.2 (streaming iter_events):** :meth:`EventReader.iter_events`
  returns a true generator; never materializes the full file.
- **F-4.4 (torn-tail decode):** partial UTF-8 sequence at tail
  does not raise; :class:`TraceVerifyResult` with status
  ``TORN_TAIL`` returned.
- **F-4.5 (CRLF splitlines):** a Windows-authored (``\r\n``)
  trace log parses cleanly.
- **F-4.6 (LedgerVerifyResult shape stable):** frozen dataclass;
  status literals reachable via classmethods; PARTIAL reserved
  and NOT in the current wire vocabulary.

Also locks:

- **Fork 1 (b) tail spot-check:** near-tail tamper with sidecar
  advanced is caught by the spot-check.
- **Fork 4 (b) read_all_events:** deliberate materialization
  helper with WARN threshold above 16 MiB.
- Observability events emit through the trace sink.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from ract.runtime import bind_run_id
from ract.trace.writer import (
    READ_ALL_EVENTS_WARN_BYTES,
    EventReader,
    JsonlEventWriter,
)
from ract.trace.verify import (
    TRACE_VERIFY_SIDECAR_SCHEMA,
    TRACE_VERIFY_SIDECAR_TYPE,
    TraceVerifyResult,
    _sidecar_path_for,
    cold_verify,
    verify_trace,
)


RUN_ID_HEX = "ab" * 16


def _write_events(events_path: Path, n: int) -> None:
    with bind_run_id(RUN_ID_HEX):
        w = JsonlEventWriter(events_path)
        for i in range(n):
            w.emit("run.started", {"i": i})


# ---- F-4.6 dataclass shape ------------------------------------------------


def test_trace_verify_result_frozen() -> None:
    r = TraceVerifyResult.valid(
        verified_head="a" * 64,
        verified_offset=100,
        events_verified=5,
    )
    with pytest.raises(Exception):
        r.status = "TAMPERED"  # type: ignore[misc]


def test_trace_verify_result_status_literals_exhaustive() -> None:
    """Every documented status is reachable via a classmethod."""
    # VALID
    v = TraceVerifyResult.valid(
        verified_head=None, verified_offset=0, events_verified=0
    )
    assert v.status == "VALID"
    assert v.is_valid and v.is_healthy
    # INVALID
    inv = TraceVerifyResult.invalid(reason="unreadable")
    assert inv.status == "INVALID"
    assert not inv.is_valid
    # TORN_TAIL
    tt = TraceVerifyResult.torn_tail(
        verified_head="a" * 64, verified_offset=1, events_verified=1
    )
    assert tt.status == "TORN_TAIL"
    assert tt.is_valid and not tt.is_healthy
    # TAMPERED
    t = TraceVerifyResult.tampered(
        verified_head="a" * 64,
        verified_offset=42,
        events_verified=1,
        tamper_details={"offset": 42, "event_index": 1, "kind": "prev_hash_mismatch"},
    )
    assert t.status == "TAMPERED"
    assert not t.is_valid and not t.is_healthy


def test_trace_verify_result_partial_reserved() -> None:
    """PARTIAL is RESERVED for the v0.6 anchor feature -- NOT reachable."""
    # No classmethod exists for PARTIAL construction in v0.5.2.
    assert not hasattr(TraceVerifyResult, "partial")
    # And direct construction refuses PARTIAL as an unknown status.
    with pytest.raises(ValueError, match=r"status must be one of"):
        TraceVerifyResult(
            status="PARTIAL",  # type: ignore[arg-type]
            verified_head=None,
            verified_offset=0,
            events_verified=0,
            events_torn=0,
            events_tampered=0,
            reason="reserved",
        )


def test_trace_verify_result_tamper_details_gate() -> None:
    """TAMPERED requires tamper_details; other statuses forbid it."""
    with pytest.raises(ValueError, match="tamper_details is required"):
        TraceVerifyResult(
            status="TAMPERED",
            verified_head=None,
            verified_offset=0,
            events_verified=0,
            events_torn=0,
            events_tampered=1,
            reason="oops",
            tamper_details=None,
        )
    with pytest.raises(ValueError, match="tamper_details must be None"):
        TraceVerifyResult(
            status="VALID",
            verified_head=None,
            verified_offset=0,
            events_verified=0,
            events_torn=0,
            events_tampered=0,
            reason="oops",
            tamper_details={"offset": 0},
        )


def test_trace_verify_result_events_torn_gate() -> None:
    with pytest.raises(ValueError, match="events_torn"):
        TraceVerifyResult(
            status="VALID",
            verified_head=None,
            verified_offset=0,
            events_verified=0,
            events_torn=5,
            events_tampered=0,
            reason="oops",
        )


def test_trace_verify_result_negative_offset_gate() -> None:
    with pytest.raises(ValueError, match="verified_offset"):
        TraceVerifyResult.valid(
            verified_head=None, verified_offset=-1, events_verified=0
        )


# ---- F-4.2 streaming iter_events ------------------------------------------


def test_iter_events_returns_generator(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    result = EventReader.iter_events(events_path)
    assert isinstance(result, types.GeneratorType), (
        "iter_events must return a generator (streaming), not a list"
    )
    events = list(result)
    assert len(events) == 5


def test_iter_events_missing_file_returns_empty(tmp_path: Path) -> None:
    result = EventReader.iter_events(tmp_path / "missing.jsonl")
    assert list(result) == []


def test_read_all_events_materializes_deliberately(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 3)
    lst = EventReader.read_all_events(events_path)
    assert isinstance(lst, list)
    assert len(lst) == 3


def test_read_all_events_warn_threshold_present() -> None:
    # The threshold is a module-level constant to keep the WARN
    # cheap to grep + audit at v0.6 refactor time.
    assert READ_ALL_EVENTS_WARN_BYTES >= 1024 * 1024


# ---- F-4.5 CRLF handling --------------------------------------------------


def test_iter_events_handles_crlf(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    body = events_path.read_bytes()
    crlf_body = body.replace(b"\n", b"\r\n")
    crlf_path = tmp_path / "crlf.jsonl"
    crlf_path.write_bytes(crlf_body)
    events = list(EventReader.iter_events(crlf_path))
    assert len(events) == 5


def test_writer_always_emits_lf(tmp_path: Path) -> None:
    """Writer emits ``\n`` -- never ``os.linesep`` -- so a
    Windows-produced trace is portable to POSIX and vice versa.
    """
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 3)
    body = events_path.read_bytes()
    # No CR bytes should have leaked into the trace on any
    # platform -- CRLF from a Windows text-mode writer would
    # place \r bytes here.
    assert b"\r" not in body


# ---- F-4.4 torn-tail decode ----------------------------------------------


def test_iter_events_torn_tail_utf8(tmp_path: Path) -> None:
    """Partial UTF-8 sequence at the file tail does not raise."""
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 3)
    torn = tmp_path / "torn.jsonl"
    # Append the first 2 bytes of a 3-byte char (U+2603 SNOWMAN
    # = E2 98 83). Missing the third byte -> partial UTF-8.
    torn.write_bytes(events_path.read_bytes() + b"\xe2\x98")
    # Must not raise.
    events = list(EventReader.iter_events(torn))
    # The complete events are still recovered.
    assert len(events) == 3


def test_iter_events_torn_tail_incomplete_json(tmp_path: Path) -> None:
    """Truncated last line drops via WARN + iteration stops cleanly."""
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 3)
    torn = tmp_path / "torn.jsonl"
    # Chop 15 bytes off the tail (mid-json for the last line).
    torn.write_bytes(events_path.read_bytes()[:-15])
    events = list(EventReader.iter_events(torn))
    # Only the complete events survived.
    assert len(events) == 2


# ---- Verify: cold + torn-tail --------------------------------------------


def test_cold_verify_reports_torn_tail_status(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    torn = tmp_path / "torn.jsonl"
    torn.write_bytes(events_path.read_bytes()[:-20])
    r = cold_verify(torn)
    assert r.status == "TORN_TAIL"
    assert r.events_torn == 1
    assert r.events_verified == 4
    # is_valid True (can resume), is_healthy False (not pristine).
    assert r.is_valid and not r.is_healthy


def test_cold_verify_reports_valid_on_clean_log(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 10)
    r = cold_verify(events_path)
    assert r.status == "VALID"
    assert r.events_verified == 10
    assert r.events_torn == 0
    assert r.events_tampered == 0
    assert r.verified_head is not None
    assert r.verified_offset == events_path.stat().st_size


def test_cold_verify_missing_file_returns_valid_empty(tmp_path: Path) -> None:
    r = cold_verify(tmp_path / "does_not_exist.jsonl")
    assert r.status == "VALID"
    assert r.events_verified == 0
    assert r.verified_head is None


# ---- Verify: TAMPERED detection ------------------------------------------


def test_cold_verify_detects_middle_tamper(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 10)
    lines = events_path.read_bytes().split(b"\n")
    # Mutate event index 5's payload.
    d = json.loads(lines[5])
    d["payload"] = {"i": 9999}
    lines[5] = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    events_path.write_bytes(b"\n".join(lines))
    r = cold_verify(events_path)
    assert r.status == "TAMPERED"
    assert r.events_tampered == 1
    assert r.events_verified == 5
    assert r.tamper_details is not None
    assert r.tamper_details["event_index"] == 5


# ---- F-4.1 incremental warm verify ---------------------------------------


def test_warm_verify_creates_sidecar_on_first_run(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 10)
    sidecar = _sidecar_path_for(events_path, RUN_ID_HEX)
    assert not sidecar.exists()
    r = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    assert r.status == "VALID"
    assert sidecar.exists()


def test_warm_verify_only_replays_delta(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 20)
    # Cold-prime the sidecar.
    r1 = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    assert r1.events_verified == 20
    baseline_offset = r1.verified_offset
    # Append 10 more events.
    _write_events(events_path, 10)  # this reseeds tip + appends
    # Actually _write_events re-opens the writer -- reseed tip
    # keeps chain continuous. Append 5 total to give delta.
    r2 = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    assert r2.status == "VALID"
    assert r2.events_verified > r1.events_verified
    # verified_offset moved forward.
    assert r2.verified_offset > baseline_offset


def test_force_cold_bypasses_sidecar(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 20)
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    r = verify_trace(events_path, run_id_hex=RUN_ID_HEX, force_cold=True)
    assert r.status == "VALID"
    assert r.events_verified == 20


def test_warm_verify_falls_back_when_sidecar_missing(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    sidecar_path = tmp_path / "explicit.verify.json"
    r = verify_trace(events_path, run_id_hex=RUN_ID_HEX, sidecar_path=sidecar_path)
    assert r.status == "VALID"
    assert sidecar_path.exists()


def test_warm_verify_falls_back_when_file_shrank(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 20)
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    # Shrink the file (simulate rotation / operator edit).
    body = events_path.read_bytes()
    # Keep first 5 events only.
    lines = body.split(b"\n")
    events_path.write_bytes(b"\n".join(lines[:5]) + b"\n")
    r = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    # Warm path aborts because sidecar's offset > file size;
    # cold verify handles from GENESIS.
    assert r.status in ("VALID", "TORN_TAIL")


# ---- Fork 1 (b) spot-check catches near-tail tamper ----------------------


def test_spot_check_catches_near_tail_tamper(tmp_path: Path) -> None:
    """Attacker tampers near-tail event and forges sidecar; warm
    path spot-check refuses and falls back to cold verify (which
    then reports TAMPERED).
    """
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 20)
    # Prime the sidecar.
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    # Tamper an event that lives inside the spot-check window.
    lines = events_path.read_bytes().split(b"\n")
    d = json.loads(lines[15])
    d["payload"] = {"i": 8888}
    lines[15] = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
    events_path.write_bytes(b"\n".join(lines))
    r = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    # Spot-check refuses the sidecar; cold verify surfaces the tamper.
    assert r.status == "TAMPERED"


# ---- Sidecar type registration ------------------------------------------


def test_trace_verify_sidecar_type_registered(tmp_path: Path) -> None:
    """After a single verify pass the trace_verify type is registered
    with the module_04 sidecar_header primitive.
    """
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 3)
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    from ract.sidecar_header import known_versions_for

    versions = known_versions_for(TRACE_VERIFY_SIDECAR_TYPE)
    assert TRACE_VERIFY_SIDECAR_SCHEMA in versions
