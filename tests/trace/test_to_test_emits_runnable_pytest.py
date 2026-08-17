"""``ract trace to-test`` emits a runnable pytest test file."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from ract.cli import main
from ract.trace.writer import JsonlEventWriter


RUN_ID_BYTES = b"\x05" * 16


def _write_synthetic_run(runs_root: Path, run_id: str) -> None:
    p = runs_root / run_id / "events.jsonl"
    w = JsonlEventWriter(p, run_id=RUN_ID_BYTES)
    w.emit("run.started", {"intent_id": "abc"})
    step = b"\x0a" * 16
    w.emit(
        "step.started",
        {
            "parent_snapshot": "aaa",
            "branch": f"rootact/step/{step.hex()}",
            "postcondition_count": 0,
            "manifest_digest": None,
            "timeout_seconds": 60,
        },
        step_id=step,
    )
    w.emit(
        "response.received",
        {
            "provider": "fake",
            "intent_id": "one",
            "response_type": "str",
            "preview": "{}",
        },
    )
    w.emit(
        "step.committed",
        {
            "outcome": "COMMITTED",
            "parent_snapshot_before": "aaa",
            "parent_snapshot_after": "ccc",
            "branch": f"rootact/step/{step.hex()}",
            "reason": "",
        },
        step_id=step,
    )
    w.emit("run.completed", {})


def test_to_test_emits_runnable_pytest(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_synthetic_run(runs, "regr")
    out = tmp_path / "test_emitted.py"

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(
            [
                "trace",
                "--runs-root",
                str(runs),
                "to-test",
                "regr",
                "--out",
                str(out),
                "--json",
            ]
        )
    assert rc == 0
    result = json.loads(buf.getvalue())
    assert Path(result["test_path"]).is_file()
    fixtures = Path(result["fixtures_dir"])
    assert (fixtures / "pinned_responses.json").is_file()
    assert (fixtures / "expected_state.json").is_file()
    assert result["response_count"] == 1
    assert result["final_snapshot"] == "ccc"

    # pytest --collect-only against the emitted file must succeed.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(out)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, (
        f"pytest --collect-only failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    # Running the emitted test must produce a green result.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-cov", str(out)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, (
        f"pytest of emitted regression test failed:\nSTDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )


# RACT 0.4.0
