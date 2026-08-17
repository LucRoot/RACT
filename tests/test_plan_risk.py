"""Tests for the static PlanRiskReport analyzer + plan.risk_assessed event."""

from __future__ import annotations

import os
from pathlib import Path

from ract.core.compile import CompilerInputs, IntentCompiler
from ract.core.loop import WorkspaceSnapshot
from ract.core.plan import (
    CURRENT_SCHEMA_VERSION,
    PlanSchema,
    StepSchema,
)
from ract.core.plan_risk import (
    HighRiskStep,
    PlanRiskReport,
    analyze_plan,
)
from ract.trace.sink import ListSink, clear_writer, set_writer


def _plan(*steps: StepSchema) -> PlanSchema:
    return PlanSchema(
        schema_version=CURRENT_SCHEMA_VERSION,
        assumption="",
        confidence=1.0,
        steps=list(steps),
    )


def test_analyze_empty_plan_zero_risk() -> None:
    report = analyze_plan(_plan())
    assert report.risk_score == 0.0
    assert report.high_risk_steps == ()


def test_analyze_plan_with_destructive_step_scores_high() -> None:
    plan = _plan(
        StepSchema(step_id="a", action="delete stale files from tmp dir"),
        StepSchema(step_id="b", action="write summary"),
    )
    report = analyze_plan(plan)
    assert report.risk_score > 0.0
    kinds = [step.risk_kind for step in report.high_risk_steps]
    assert "destructive" in kinds
    # Non-destructive step "write summary" does NOT flag.
    step_a_flags = [s for s in report.high_risk_steps if s.step_id == "a"]
    step_b_flags = [s for s in report.high_risk_steps if s.step_id == "b"]
    assert step_a_flags
    assert not step_b_flags


def test_analyze_plan_with_manifest_downgrades_within_tier() -> None:
    """A manifest that already permits the plan's tier halves the tier score."""
    from ract.security.manifest import CapabilityManifest, TierPolicy

    manifest = CapabilityManifest(
        run_id="test",
        tiers=TierPolicy(default=2),
    )
    plan = _plan(StepSchema(step_id="s", action="task", tier="T2"))
    with_manifest = analyze_plan(plan, manifest=manifest)
    without_manifest = analyze_plan(plan, manifest=None)
    tier_hits_w = [
        s
        for s in with_manifest.high_risk_steps
        if s.risk_kind == "high_capability_tier"
    ]
    tier_hits_wo = [
        s
        for s in without_manifest.high_risk_steps
        if s.risk_kind == "high_capability_tier"
    ]
    assert tier_hits_w and tier_hits_wo
    assert tier_hits_w[0].score < tier_hits_wo[0].score


def test_plan_risk_event_emitted_by_compile() -> None:
    """IntentCompiler.compile emits plan.risk_assessed when plan_for_risk is supplied."""
    sink = ListSink(run_id=os.urandom(16))
    clear_writer()
    set_writer(sink)
    try:
        compiler = IntentCompiler()
        ws = WorkspaceSnapshot(files={}, timestamp=0.0)
        plan = _plan(StepSchema(step_id="s", action="delete records"))
        compiler.compile(
            "task",
            ws,
            inputs=CompilerInputs(plan_for_risk=plan),
        )
        kinds = [e.kind for e in sink.events]
        assert "plan.risk_assessed" in kinds
        risk = next(e for e in sink.events if e.kind == "plan.risk_assessed")
        assert risk.payload["risk_score"] > 0.0
        assert any(
            s["risk_kind"] == "destructive" for s in risk.payload["high_risk_steps"]
        )
    finally:
        clear_writer()


def test_plan_risk_no_event_without_plan_for_risk() -> None:
    """Substrate callers who don't supply plan_for_risk see no plan.risk_assessed."""
    sink = ListSink(run_id=os.urandom(16))
    clear_writer()
    set_writer(sink)
    try:
        compiler = IntentCompiler()
        ws = WorkspaceSnapshot(files={}, timestamp=0.0)
        compiler.compile("task", ws)
        kinds = [e.kind for e in sink.events]
        assert "plan.risk_assessed" not in kinds
    finally:
        clear_writer()


def test_ract_plan_analyze_reads_event_and_prints_report(
    tmp_path: Path, capsys
) -> None:
    """`ract plan analyze <session>` reads events.jsonl and prints the report."""
    from ract.cli import _plan_command
    from ract.trace.writer import JsonlEventWriter

    session = "test-session-001"
    events_dir = tmp_path / "runs" / session
    events_dir.mkdir(parents=True)
    events_path = events_dir / "events.jsonl"

    writer = JsonlEventWriter(events_path, run_id=os.urandom(16))
    plan_id = os.urandom(16)
    report = PlanRiskReport(
        plan_id=plan_id,
        risk_score=0.42,
        high_risk_steps=(
            HighRiskStep(
                step_id="s",
                risk_kind="destructive",
                score=0.7,
                rationale="rm -rf",
            ),
        ),
        suggestions=("dry-run first",),
    )
    writer.emit("plan.risk_assessed", report.to_payload())

    exit_code = _plan_command(
        ["analyze", session, "--runs-dir", str(tmp_path / "runs")]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "risk_score: 0.420" in captured.out
    assert "destructive" in captured.out
    assert "dry-run first" in captured.out


def test_ract_plan_analyze_json_mode(tmp_path: Path, capsys) -> None:
    from ract.cli import _plan_command
    from ract.trace.writer import JsonlEventWriter
    import json

    session = "s2"
    events_dir = tmp_path / "runs" / session
    events_dir.mkdir(parents=True)
    events_path = events_dir / "events.jsonl"
    writer = JsonlEventWriter(events_path, run_id=os.urandom(16))
    writer.emit(
        "plan.risk_assessed",
        PlanRiskReport(risk_score=0.1).to_payload(),
    )

    exit_code = _plan_command(
        ["analyze", session, "--runs-dir", str(tmp_path / "runs"), "--json"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    parsed = json.loads(captured.out)
    assert parsed["risk_score"] == 0.1


# RACT 0.4.1
