"""Fork at a chosen step of a synthetic run."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from ract.cli import main
from ract.trace.writer import JsonlEventWriter


RUN_ID_BYTES = b"\x03" * 16


def _write_five_step_run(runs_root: Path, run_id: str) -> list[bytes]:
    p = runs_root / run_id / "events.jsonl"
    w = JsonlEventWriter(p, run_id=RUN_ID_BYTES)
    w.emit("run.started", {"intent_id": "abc"})
    step_ids: list[bytes] = []
    parent = "aaa"
    for i in range(5):
        step = bytes([i + 1]) * 16
        step_ids.append(step)
        w.emit(
            "step.started",
            {
                "parent_snapshot": parent,
                "branch": f"rootact/step/{step.hex()}",
                "postcondition_count": 0,
                "manifest_digest": None,
                "timeout_seconds": 60,
            },
            step_id=step,
        )
        after = f"snap{i + 1}"
        w.emit(
            "step.committed",
            {
                "outcome": "COMMITTED",
                "parent_snapshot_before": parent,
                "parent_snapshot_after": after,
                "branch": f"rootact/step/{step.hex()}",
                "reason": "",
            },
            step_id=step,
        )
        parent = after
    w.emit("run.completed", {})
    return step_ids


def test_fork_at_step_three_replays_prefix_only(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    step_ids = _write_five_step_run(runs, "fork1")
    third = step_ids[2].hex()  # fork after step 3 completes

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(
            [
                "trace",
                "--runs-root",
                str(runs),
                "fork",
                "fork1",
                "--at",
                f"step:{third}",
                "--with",
                "alternative intent",
                "--json",
            ]
        )
    assert rc == 0
    header = json.loads(buf.getvalue())
    assert header["kind"] == "fork"
    assert header["source_run_id"] == "fork1"
    assert header["fork_at_step"] == third
    assert header["alternative_intent"] == "alternative intent"
    # Prefix = run.started + 3 * (step.started + step.committed) = 7
    assert header["prefix_event_count"] == 7


def test_fork_unknown_step_errors(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_five_step_run(runs, "fork2")
    bogus = ("f" * 32)

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(
            [
                "trace",
                "--runs-root",
                str(runs),
                "fork",
                "fork2",
                "--at",
                f"step:{bogus}",
                "--with",
                "x",
                "--json",
            ]
        )
    assert rc == 2


# RACT 0.4.0
