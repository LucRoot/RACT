"""Verify LoopController._maybe_emit_plan_rewritten emits the event.

Exercises the emit path directly rather than running a full LoopController
iteration; the loop's iteration wiring is validated separately.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ract.executor import ExecutionReport
from ract.loop_controller import LoopController
from ract.manager import Plan, Step
from ract.trace.sink import ListSink, clear_writer, set_writer


def _fresh_controller(tmp_path: Path) -> LoopController:
    cfg = tmp_path / "ract.yaml"
    cfg.write_text("providers: {}\n", encoding="utf-8")
    return LoopController(config_path=cfg)


def _report_with_plan(plan: Plan) -> ExecutionReport:
    return ExecutionReport(
        intent="",
        step_results=[],
        assumptions=[],
        plan=plan,
    )


def test_plan_rewritten_event_emitted(tmp_path: Path) -> None:
    sink = ListSink(run_id=os.urandom(16))
    clear_writer()
    set_writer(sink)
    try:
        controller = _fresh_controller(tmp_path)

        p1 = Plan(
            assumption="a",
            confidence=1.0,
            steps=[Step(action="v1", provider_hint="", expected_artifact="")],
        )
        p2 = Plan(
            assumption="a",
            confidence=1.0,
            steps=[Step(action="v2", provider_hint="", expected_artifact="")],
        )

        # First iteration primes the previous-plan slot; no event yet.
        controller._maybe_emit_plan_rewritten(_report_with_plan(p1))
        assert [e.kind for e in sink.events] == []

        # Second iteration diffs against p1 and emits.
        controller._maybe_emit_plan_rewritten(_report_with_plan(p2))
        kinds = [e.kind for e in sink.events]
        assert "plan.rewritten" in kinds

        rewritten = [e for e in sink.events if e.kind == "plan.rewritten"]
        assert len(rewritten) == 1
        payload: dict[str, Any] = rewritten[0].payload
        # Content-hash keying: content change surfaces as removed + added
        # (no persistent step identity in ract.manager.Plan).
        assert len(payload["removed_step_ids"]) == 1
        assert len(payload["added_step_ids"]) == 1
        assert payload["modified_step_ids"] == []
    finally:
        clear_writer()


def test_plan_rewritten_not_emitted_when_identical(tmp_path: Path) -> None:
    sink = ListSink(run_id=os.urandom(16))
    clear_writer()
    set_writer(sink)
    try:
        controller = _fresh_controller(tmp_path)

        p = Plan(
            assumption="a",
            confidence=1.0,
            steps=[Step(action="v1", provider_hint="", expected_artifact="")],
        )
        controller._maybe_emit_plan_rewritten(_report_with_plan(p))
        controller._maybe_emit_plan_rewritten(_report_with_plan(p))
        assert [e.kind for e in sink.events if e.kind == "plan.rewritten"] == []
    finally:
        clear_writer()


# RACT 0.4.1
