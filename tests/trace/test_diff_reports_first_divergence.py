"""Structured diff surfaces the first divergent event."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from ract.cli import main
from ract.trace.writer import JsonlEventWriter


RUN_ID_BYTES = b"\x04" * 16


def _write(runs_root: Path, run_id: str, second_intent: str) -> None:
    p = runs_root / run_id / "events.jsonl"
    w = JsonlEventWriter(p, run_id=RUN_ID_BYTES)
    w.emit("run.started", {"intent_id": "abc"})
    w.emit(
        "prompt.sent",
        {
            "provider": "fake",
            "response_shape": "json_schema",
            "intent_id": second_intent,
            "prompt_chars": 50,
        },
    )
    w.emit("run.completed", {})


def test_diff_identical_runs_reports_no_divergence(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write(runs, "a", "same")
    _write(runs, "b", "same")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["trace", "--runs-root", str(runs), "diff", "a", "b", "--json"])
    assert rc == 0
    result = json.loads(buf.getvalue())
    assert result["diverged"] is False
    assert result["first_divergence"] is None


def test_diff_diverging_runs_surfaces_first_divergence(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write(runs, "a", "left")
    _write(runs, "b", "right")

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["trace", "--runs-root", str(runs), "diff", "a", "b", "--json"])
    assert rc == 0
    result = json.loads(buf.getvalue())
    assert result["diverged"] is True
    div = result["first_divergence"]
    # Divergence lives on the ``prompt.sent`` event (index 1).
    assert div["index"] == 1
    assert div["a"]["kind"] == "prompt.sent"
    assert div["a"]["payload"]["intent_id"] == "left"
    assert div["b"]["payload"]["intent_id"] == "right"


# RACT 0.4.0
