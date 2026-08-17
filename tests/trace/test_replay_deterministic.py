"""Deterministic replay: ``ract trace replay`` reconstructs the reel."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from ract.cli import main
from ract.trace.writer import JsonlEventWriter


RUN_ID_BYTES = b"\x02" * 16


def _write_synthetic_run(runs_root: Path, run_id: str) -> None:
    p = runs_root / run_id / "events.jsonl"
    w = JsonlEventWriter(p, run_id=RUN_ID_BYTES)
    w.emit("run.started", {"intent_id": "abc"})
    step = b"s" * 16
    w.emit(
        "step.started",
        {
            "parent_snapshot": "aaa",
            "branch": "rootact/step/aa",
            "postcondition_count": 1,
            "manifest_digest": None,
            "timeout_seconds": 60,
        },
        step_id=step,
    )
    w.emit(
        "prompt.sent",
        {
            "provider": "fake",
            "response_shape": "json_schema",
            "intent_id": "step1",
            "prompt_chars": 100,
        },
    )
    w.emit(
        "response.received",
        {
            "provider": "fake",
            "intent_id": "step1",
            "response_type": "str",
            "preview": '{"kind":"read_file"}',
        },
    )
    w.emit(
        "step.committed",
        {
            "outcome": "COMMITTED",
            "parent_snapshot_before": "aaa",
            "parent_snapshot_after": "bbb",
            "branch": "rootact/step/aa",
            "reason": "",
        },
        step_id=step,
    )
    w.emit("run.completed", {})


def test_replay_reconstructs_reel(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_synthetic_run(runs, "r1")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["trace", "--runs-root", str(runs), "replay", "r1", "--json"])
    assert rc == 0

    out = json.loads(buf.getvalue())
    assert out["summary"]["events_replayed"] == 6
    assert out["summary"]["reel_length"] == 2
    assert out["summary"]["final_snapshot"] == "bbb"
    reel = out["reel"]
    assert reel[0]["kind"] == "prompt.sent"
    assert reel[0]["intent_id"] == "step1"
    assert reel[1]["kind"] == "response.received"


def test_replay_until_step_truncates(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_synthetic_run(runs, "r2")
    step_hex = ("s" * 16).encode("utf-8").hex()[:32]  # b'ssss...'.hex()
    step_hex = (b"s" * 16).hex()

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(
            [
                "trace",
                "--runs-root",
                str(runs),
                "replay",
                "r2",
                "--until",
                f"step:{step_hex}",
                "--json",
            ]
        )
    assert rc == 0
    out = json.loads(buf.getvalue())
    # After the terminal ``step.committed``, the trailing ``run.completed``
    # is truncated.
    assert out["summary"]["events_replayed"] == 5


# RACT 0.4.0
