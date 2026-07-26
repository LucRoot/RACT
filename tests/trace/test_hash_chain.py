"""Hash-chain invariants for the trace substrate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.trace.events import ChainBrokenError, EventChain, LEGAL_EVENT_KINDS
from ract.trace.writer import EventReader, JsonlEventWriter, rebuild_hash


RUN_ID = b"\x01" * 16


def test_appending_valid_event_extends_chain() -> None:
    chain = EventChain(run_id=RUN_ID)
    ev = chain.build_next(kind="run.started", payload={"a": 1})
    chain.append(ev)
    assert len(chain.events) == 1
    assert chain.tip_hash == ev.hash


def test_appending_with_wrong_prev_hash_raises() -> None:
    chain = EventChain(run_id=RUN_ID)
    ev = chain.build_next(kind="run.started", payload={"a": 1})
    chain.append(ev)
    # Build a second event but do NOT append it; then reset the chain
    # tip artificially and try to append — the prev_hash link must fail.
    second = chain.build_next(kind="run.completed", payload={})
    chain.tip_hash = b"\xff" * 32
    with pytest.raises(ChainBrokenError):
        chain.append(second)


def test_tampered_middle_event_detected_on_load(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    w = JsonlEventWriter(p, run_id=RUN_ID)
    w.emit("run.started", {"n": 1})
    w.emit("run.completed", {"n": 2})
    # Tamper: rewrite the middle line's payload but keep its hash — the
    # rehash check inside ``EventChain.append`` will catch the swap.
    lines = p.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["payload"] = {"n": 999}
    lines[0] = json.dumps(first, sort_keys=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ChainBrokenError):
        EventReader.load(p)


def test_event_kind_vocabulary_is_closed() -> None:
    # SUBSTRATE §6.3 — every kind emitted anywhere in the codebase must
    # be in this closed set. Sanity-check the set is what module_05 shipped.
    assert "run.started" in LEGAL_EVENT_KINDS
    assert "sandbox.unenforced" in LEGAL_EVENT_KINDS
    assert "rootknot.verified" in LEGAL_EVENT_KINDS
    assert "shell_exec" not in LEGAL_EVENT_KINDS  # never added


def test_rebuild_hash_matches_declared_hash(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    w = JsonlEventWriter(p, run_id=RUN_ID)
    ev = w.emit("run.started", {"a": 1})
    assert rebuild_hash(ev) == ev.hash


# RACT 0.4.0
