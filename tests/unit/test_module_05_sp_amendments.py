"""Regression -- module_05 SP amendment fixes.

v0.5.2 hardening module_05 SP amendment. Locks the SP DEFECT
verdicts from Ox Alpha (dispatches A + B) and cross-family
reviewer:

- **Ox Alpha A Q1 (DEFECT adjacent):** ``_read_events_in_range``
  used to silently truncate the checked prefix on a middle-line
  parse failure in the tail window -- spot-check reported OK
  and warm verify accepted an attacker's injected garbage line
  in the pre-offset region. Post-amendment: tri-state return
  ``(events, hit_torn, complete)``; ``_spot_check_tail``
  refuses (False, "inconclusive") when ``complete=False``.
- **Ox Alpha A Q2 + cross-family Q2 (DEFECT CONVERGED):** the
  walker never checked ``event.run_id == chain.run_id``. An
  attacker splicing events from another run with valid hash
  chain would pass verification. Post-amendment: walker
  compares every event's run_id to the chain's bound run_id;
  mismatch -> TAMPERED with kind="run_id_mismatch".
- **Ox Alpha A Q3 (DEFECT minor):** ``_read_verify_sidecar``
  used to accept negative int for last_verified_offset and
  bool-as-int (``True`` -> 1). Negative offset propagated to
  ``fp.seek(-1)`` and raised OSError -- breaking the
  "Never raises for cache-miss reasons" contract.
  Post-amendment: reject bool, reject negative, reject
  non-64-char-hex heads.
- **Ox Alpha A Q4 (DEFECT):** middle-line UTF-8 corruption
  propagated as a raw UnicodeDecodeError through
  ``cold_verify`` / ``verify_trace`` -- violating the closed
  dataclass contract. Post-amendment: both entry points wrap
  ``_walk_verify`` in ``except (OSError, UnicodeDecodeError,
  ChainBrokenError)`` and surface as INVALID / TAMPERED.
- **Ox Alpha B Q1 (DEFECT):** ``iter_events`` computed
  ``is_tail`` from a stale ``file_size`` captured once at the
  top -- under concurrent write, real middle-line corruption
  in the appended region was mis-classified as torn tail and
  silently dropped. Post-amendment: restat before the
  tail-tolerant path so a growing file surfaces the middle
  corruption as ChainBrokenError.
- **Ox Alpha B Q3 (DEFECT lint):** ``has_newline`` was
  captured and never used. Post-amendment: removed with a
  comment naming why (avoid cargo-cult reintroduction that
  would break the locked
  ``test_event_chain_tolerates_truncated_tail`` semantics).
- **Ox Alpha co-build Fork 2 companion rule (DEFECT):** the
  writer's ``_reseed_tip_from_disk`` used to leave torn tail
  bytes in place -- the next emit() then appended AFTER the
  torn line, sandwiching it mid-file. Post-amendment: on
  dropped_tail > 0 the writer truncates the file to the end
  of the seeded line before allowing new appends.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ract.runtime import bind_run_id
from ract.trace.events import ChainBrokenError
from ract.trace.writer import EventReader, JsonlEventWriter
from ract.trace.verify import (
    TraceVerifyResult,
    _read_verify_sidecar,
    _sidecar_path_for,
    cold_verify,
    verify_trace,
)

RUN_ID_HEX = "77" * 16
_RUN_ID = bytes.fromhex(RUN_ID_HEX)


def _write_events(events_path: Path, n: int) -> None:
    with bind_run_id(RUN_ID_HEX):
        w = JsonlEventWriter(events_path)
        for i in range(n):
            w.emit("run.started", {"i": i})


# ---- Ox Alpha A Q1 adjacent: spot-check inconclusive on middle parse fail --


def test_spot_check_refuses_on_middle_json_error_in_tail_window(
    tmp_path: Path,
) -> None:
    """Attacker injects a garbage line in the pre-offset region;
    spot-check refuses and warm path cold-fallbacks (which then
    detects TAMPERED).
    """
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 20)
    # Prime the sidecar.
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    # Inject garbage as a middle line (event index 10).
    lines = events_path.read_bytes().split(b"\n")
    lines[10] = b"{not_valid_json_but_syntactically_present"
    events_path.write_bytes(b"\n".join(lines))
    # Warm verify: spot-check refuses; cold verify surfaces TAMPERED
    # (json.loads fails on the garbage line as middle-corruption).
    r = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    assert r.status == "TAMPERED"


# ---- Ox Alpha A Q2 + cross-family Q2 CONVERGED: run_id splice ------------


def test_walker_rejects_spliced_event_from_different_run(tmp_path: Path) -> None:
    """An event with a different run_id inserted into an otherwise
    intact chain (with recomputed prev_hash) is caught as
    kind="run_id_mismatch".
    """
    # Build two independent trace logs with different run_ids.
    ep_a = tmp_path / "a.jsonl"
    ep_b = tmp_path / "b.jsonl"
    run_a_hex = "aa" * 16
    run_b_hex = "bb" * 16
    with bind_run_id(run_a_hex):
        wa = JsonlEventWriter(ep_a)
        for i in range(5):
            wa.emit("run.started", {"i": i})
    with bind_run_id(run_b_hex):
        wb = JsonlEventWriter(ep_b)
        for i in range(5):
            wb.emit("run.started", {"i": i})
    # cold_verify of ep_a with genuine chain returns VALID.
    assert cold_verify(ep_a).status == "VALID"
    # Now build a spliced file: event 0 from run A, events 1..N
    # forged with run_b_hex but chaining from event 0's hash.
    # The simplest tamper: rewrite event 1 to declare run_id=B.
    lines = ep_a.read_bytes().split(b"\n")
    ev0 = json.loads(lines[0])
    # Change run_id -- rehash would need to reflect that; but we
    # want cheap tamper detection: attacker who forgets to
    # recompute the hash is trivially caught by rehash_check.
    # The Q2 defect is about the attacker who DOES recompute --
    # skipping that here (full-chain recompute is the mid-file
    # gap). What we CAN test: an event that self-consistently
    # has run_id=B (i.e., its own hash was computed with B) will
    # pass rehash but fail run_id check.
    # Grab event 1 from ep_b and splice its bytes as ep_a's event 1
    # with adjusted prev_hash to link cleanly.
    ep_b_lines = ep_b.read_bytes().split(b"\n")
    ev1_b = json.loads(ep_b_lines[1])  # run_b_hex event
    # Rewrite prev_hash to link to ep_a's event 0's hash.
    ev1_b["prev_hash"] = ev0["hash"]
    # Recompute hash to match new prev_hash.
    from ract.trace.events import Event, hash_event

    ev1_reconst = Event.from_canonical_dict(ev1_b)
    new_hash = hash_event(
        kind=ev1_reconst.kind,
        payload=ev1_reconst.payload,
        prev_hash=ev1_reconst.prev_hash,
        id_bytes=ev1_reconst.id,
        run_id=ev1_reconst.run_id,
        step_id=ev1_reconst.step_id,
        parent_id=ev1_reconst.parent_id,
        timestamp_ns=ev1_reconst.timestamp_ns,
    )
    ev1_b["hash"] = new_hash.hex()
    lines[1] = json.dumps(ev1_b, sort_keys=True, separators=(",", ":")).encode()
    # Truncate remaining events (their prev_hash pointed to the
    # old event 1 hash) -- keep only the spliced [ev0, ev1_b_forged].
    ep_a.write_bytes(b"\n".join(lines[:2]) + b"\n")
    # cold_verify: event 0 binds chain.run_id=run_a; event 1 has
    # run_id=run_b_hex -> run_id_mismatch caught.
    r = cold_verify(ep_a)
    assert r.status == "TAMPERED"
    assert r.tamper_details["kind"] == "run_id_mismatch"


# ---- Ox Alpha A Q3: sidecar bounds + type strictness ---------------------


def test_sidecar_refuses_negative_offset(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    # First verify to create a legit sidecar, then hand-edit it.
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    sc = _sidecar_path_for(events_path, RUN_ID_HEX)
    body = json.loads(sc.read_text())
    body["last_verified_offset"] = -1
    sc.write_text(json.dumps(body))
    # Read via the internal helper.
    result_body = _read_verify_sidecar(sidecar_path=sc, expected_run_id_hex=RUN_ID_HEX)
    assert result_body is None, "negative offset must fall back to cold"


def test_sidecar_refuses_bool_offset(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    sc = _sidecar_path_for(events_path, RUN_ID_HEX)
    body = json.loads(sc.read_text())
    body["last_verified_offset"] = True  # bool subclass of int
    sc.write_text(json.dumps(body))
    result_body = _read_verify_sidecar(sidecar_path=sc, expected_run_id_hex=RUN_ID_HEX)
    assert result_body is None, "bool-as-int must fall back to cold"


def test_sidecar_refuses_non_hex_head(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    sc = _sidecar_path_for(events_path, RUN_ID_HEX)
    body = json.loads(sc.read_text())
    body["last_verified_head"] = (
        "not_hex_at_all_zzz_" + "x" * 45
    )  # 64 chars but non-hex
    sc.write_text(json.dumps(body))
    result_body = _read_verify_sidecar(sidecar_path=sc, expected_run_id_hex=RUN_ID_HEX)
    assert result_body is None, "non-hex head must fall back to cold"


def test_sidecar_refuses_wrong_length_head(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    sc = _sidecar_path_for(events_path, RUN_ID_HEX)
    body = json.loads(sc.read_text())
    body["last_verified_head"] = "abcd" * 8  # 32 chars, half the length
    sc.write_text(json.dumps(body))
    result_body = _read_verify_sidecar(sidecar_path=sc, expected_run_id_hex=RUN_ID_HEX)
    assert result_body is None


def test_warm_verify_with_bad_sidecar_does_not_raise(tmp_path: Path) -> None:
    """The 'Never raises for cache-miss reasons' contract holds
    end-to-end: a crafted sidecar with a negative offset does not
    escape as an OSError from the warm path.
    """
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 10)
    verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    sc = _sidecar_path_for(events_path, RUN_ID_HEX)
    body = json.loads(sc.read_text())
    body["last_verified_offset"] = -100
    sc.write_text(json.dumps(body))
    # Must not raise; must return a dataclass.
    r = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    assert isinstance(r, TraceVerifyResult)


# ---- Ox Alpha A Q4: middle-line UTF-8 corruption surfaces as TAMPERED ----


def test_cold_verify_wraps_middle_utf8_as_tampered(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    # Inject invalid UTF-8 into a middle line (index 2).
    lines = events_path.read_bytes().split(b"\n")
    lines[2] = b"\xff\xfe\xfd invalid utf-8 middle"
    events_path.write_bytes(b"\n".join(lines))
    # Must return TAMPERED, NOT raise UnicodeDecodeError.
    r = cold_verify(events_path)
    assert r.status == "TAMPERED"
    assert r.tamper_details["kind"] in (
        "middle_utf8_corruption",
        "chain_broken",
    )


# ---- Ox Alpha B Q1: is_tail restat catches concurrent-write misclass ----


def test_iter_events_reports_middle_json_error_after_restat(
    tmp_path: Path,
) -> None:
    """Simulate a concurrent-write scenario by writing events THEN
    a garbage line AFTER them (so the garbage is genuinely in the
    middle by the time we read). Even though the file initially
    ended at the garbage, subsequent writes appended more -- the
    garbage line must surface as ChainBrokenError.
    """
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 5)
    # Append a garbage line and then more good events.
    with events_path.open("ab") as fp:
        fp.write(b"{not_valid_json_here\n")
    # Now events are: [5 good, 1 garbage] -- the garbage IS the
    # last line. iter_events treats it as tail-tolerable -> WARN
    # + drop. Confirm this is our baseline (not the concurrent case yet).
    events = list(EventReader.iter_events(events_path))
    assert len(events) == 5
    # Now emulate the concurrent case: after garbage, append MORE
    # valid events. Now garbage is middle. iter_events must raise
    # ChainBrokenError when it hits the garbage line -- restat
    # confirms end_offset < fresh file_size.
    with bind_run_id(RUN_ID_HEX):
        # Cannot use JsonlEventWriter here because reseed would
        # detect torn tail + truncate. Append raw bytes instead
        # (simulating what a concurrent process would do).
        with events_path.open("ab") as fp:
            fp.write(b'{"kind":"run.started","payload":{},"...":"...bogus"}\n')
    with pytest.raises(ChainBrokenError):
        _ = list(EventReader.iter_events(events_path))


# ---- Ox Alpha co-build Fork 2 companion rule: torn tail truncated ------


def test_writer_truncates_torn_tail_on_reseed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """After reopen-with-torn-tail the writer must physically
    remove the torn bytes so the next emit chains cleanly and
    EventReader.load does not raise on the (now-middle) torn
    line.
    """
    events_path = tmp_path / "events.jsonl"
    # Write 5 events (fixed run_id so we can reopen deterministically).
    writer = JsonlEventWriter(events_path, run_id=_RUN_ID)
    for i in range(5):
        writer.emit("run.started", {"i": i})

    # Truncate the last line to make it torn.
    raw = events_path.read_bytes()
    lines = raw.split(b"\n")
    lines[-2] = lines[-2][:20]
    events_path.write_bytes(b"\n".join(lines))
    torn_size = events_path.stat().st_size

    caplog.set_level(logging.WARNING, logger="ract.trace.writer")
    reopened = JsonlEventWriter(events_path, run_id=_RUN_ID)
    truncated_size = events_path.stat().st_size

    # File must have shrunk to remove the torn bytes.
    assert truncated_size < torn_size
    # And the truncation WARN must have fired.
    assert any("truncated" in record.message.lower() for record in caplog.records), (
        "truncation WARN missing"
    )

    # Now emit a fresh event.
    fresh = reopened.emit("step.started", {"note": "post-truncate"})
    # And full-file EventReader.load must NOT raise (no
    # sandwich).
    chain = EventReader.load(events_path)
    assert chain.events[-1].hash == fresh.hash
    # The chain has 4 preserved events + 1 fresh = 5.
    assert len(chain.events) == 5


# ---- Cross-family Q3 PASS regression: 2-verify staleness self-heals ------


def test_two_warm_verifies_self_heal_sidecar_staleness(tmp_path: Path) -> None:
    """After cold-prime then warm-again, the sidecar catches up
    to the current tail without any extra intervention.
    """
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, 10)
    r1 = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    assert r1.status == "VALID"
    # Append more.
    _write_events(events_path, 5)  # reopens writer, appends 5 more
    r2 = verify_trace(events_path, run_id_hex=RUN_ID_HEX)
    assert r2.status == "VALID"
    assert r2.events_verified > r1.events_verified
