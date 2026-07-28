"""``RunReporter`` derives its summary from the event log alone.

SUBSTRATE §6.5. The reporter no longer holds run state; feeding it a
synthetic event log produces the expected summary shape.
"""

from __future__ import annotations

from pathlib import Path

from ract.run_reporter import RunReporter
from ract.trace.writer import JsonlEventWriter


RUN_ID_BYTES = b"\x06" * 16


def _write(runs_root: Path, run_id: str) -> Path:
    p = runs_root / run_id / "events.jsonl"
    w = JsonlEventWriter(p, run_id=RUN_ID_BYTES)
    w.emit("run.started", {"intent_id": "abc"})
    step_a = b"\x11" * 16
    step_b = b"\x22" * 16
    w.emit(
        "step.started",
        {
            "parent_snapshot": "aaa",
            "branch": f"rootact/step/{step_a.hex()}",
            "postcondition_count": 1,
            "manifest_digest": None,
            "timeout_seconds": 60,
        },
        step_id=step_a,
    )
    w.emit(
        "predicate.evaluated",
        {
            "predicate_id": "p1",
            "kind": "test",
            "required": True,
            "ok": True,
            "reason": "",
            "duration_ns": 12,
        },
    )
    w.emit(
        "step.committed",
        {
            "outcome": "COMMITTED",
            "parent_snapshot_before": "aaa",
            "parent_snapshot_after": "bbb",
            "branch": f"rootact/step/{step_a.hex()}",
            "reason": "",
        },
        step_id=step_a,
    )
    w.emit(
        "step.started",
        {
            "parent_snapshot": "bbb",
            "branch": f"rootact/step/{step_b.hex()}",
            "postcondition_count": 1,
            "manifest_digest": None,
            "timeout_seconds": 60,
        },
        step_id=step_b,
    )
    w.emit(
        "predicate.evaluated",
        {
            "predicate_id": "p2",
            "kind": "test",
            "required": True,
            "ok": False,
            "reason": "expected pass, got fail",
            "duration_ns": 30,
        },
    )
    w.emit(
        "step.rolled_back",
        {
            "outcome": "ROLLED_BACK",
            "parent_snapshot_before": "bbb",
            "parent_snapshot_after": "bbb",
            "branch": f"rootact/step/{step_b.hex()}",
            "reason": "post-condition failed",
        },
        step_id=step_b,
    )
    w.emit(
        "handshake.requested",
        {
            "milestone_id": "m1",
            "status": "pending",
            "description": "needs review",
            "reason": "",
        },
    )
    w.emit(
        "run.aborted",
        {
            "termination_cause": "PROVIDER_TIMEOUT",
            "reason": "second-strike",
            "duration_ns": 999,
        },
    )
    return p


def test_projection_derives_summary_from_event_log(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    events_path = _write(runs, "r1")

    projected = RunReporter.project_events(events_path)

    assert projected["final_decision"] == "aborted"
    assert projected["termination_cause"] == "PROVIDER_TIMEOUT"
    assert projected["events_projected"] == 9
    assert len(projected["iterations"]) == 2
    assert projected["iterations"][0]["decision"] == "COMMITTED"
    assert projected["iterations"][1]["decision"] == "ROLLED_BACK"
    assert projected["handshake_milestones"] == ["m1"]
    metrics = projected["metrics"]
    assert metrics["predicate_pass"] == 1
    assert metrics["predicate_fail"] == 1
    assert metrics["event_count"] == 9
    # counts_by_kind is derived data, not raw state.
    assert projected["counts_by_kind"]["predicate.evaluated"] == 2


def test_reporter_has_no_direct_executor_state(tmp_path: Path) -> None:
    """The reporter reads only the log — its API surface is projection-only."""
    reporter = RunReporter(project_dir=tmp_path)
    # Attributes that would indicate direct executor state:
    assert not hasattr(reporter, "iterations")
    assert not hasattr(reporter, "_state")
    assert not hasattr(reporter, "record_iteration")
    # The projection API is the module_05 surface.
    assert callable(RunReporter.project_events)
    assert callable(RunReporter.render_projected_events)


def test_render_projected_events_renders_human_text(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    events_path = _write(runs, "r2")
    rendered = RunReporter.render_projected_events(events_path)
    assert "Termination cause: PROVIDER_TIMEOUT" in rendered
    assert "Iterations (2)" in rendered
    assert "COMMITTED" in rendered
    assert "ROLLED_BACK" in rendered


# RACT 0.4.0
