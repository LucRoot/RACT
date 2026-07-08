from __future__ import annotations

_ROOT_KNOT = object()

import pytest
from pathlib import Path

from typing import Any

from rootact.run_mode import (
    RunMode,
    RunModeOrchestrator,
    _ROOT_KNOT as _RUN_MODE_ROOT_KNOT,
)
from rootact.session_store import SessionStore
from rootact.harness import Harness
from rootact.manager import Plan, Step
from rootact.approval_queue_cli import ApprovalQueueCLI


class FakeStep(Step):
    def __init__(self, action: str, provider_hint: str, expected_artifact: str) -> None:
        super().__init__(action, provider_hint, expected_artifact)


class FakePlan(Plan):
    def __init__(self, assumption: str, confidence: float, steps: list[Step]) -> None:
        super().__init__(assumption, confidence, steps)


class FakeHarness(Harness):
    def __init__(self, plan: FakePlan) -> None:
        self._plan = plan
        self.executed_steps: list[str] = []
        self.plans_requested = 0

    def build_plan(self, intent: str) -> Plan:
        self.plans_requested += 1
        return self._plan

    def run_plan(self, plan: Plan) -> dict[str, Any]:
        for step in plan.steps:
            self.run_step(step)
        return {"executed": self.executed_steps}

    def run_step(self, step: Step) -> None:
        self.executed_steps.append(step.action)

    def finalize(self) -> dict[str, Any]:
        return {"finalized": True}

    def plan_only(self, plan: Plan) -> dict[str, Any]:
        return {"plan_preview": [s.action for s in plan.steps]}

    def build_plan_from_state(self, state, intent: str) -> Plan:
        return self._plan


class FakeApprovalQueueCLI(ApprovalQueueCLI):
    def __init__(self, approvals: dict[str, bool]) -> None:
        super().__init__()
        self.approvals = approvals

    def prompt(self, action: str) -> bool:
        return self.approvals.get(action, False)


@pytest.fixture
def orchestrator() -> RunModeOrchestrator:
    return RunModeOrchestrator()


def test_yolo_mode_execute_without_approval(orchestrator: RunModeOrchestrator) -> None:
    harness = FakeHarness(FakePlan("test", 1.0, []))
    report = orchestrator.orchestrate("test_intent", RunMode.YOLO, harness)
    assert report is not None


def test_auto_mode_consults_approval_queue_for_high_artifact(
    orchestrator: RunModeOrchestrator,
) -> None:
    approvals = {"high_step": True}
    approval_queue = FakeApprovalQueueCLI(approvals)
    step = FakeStep("high_step", "hint", "high_artifact")
    plan = FakePlan("test", 1.0, [step])
    harness = FakeHarness(plan)
    _ = orchestrator.orchestrate("test_intent", RunMode.AUTO, harness, approval_queue)
    assert len(harness.executed_steps) == 1


def test_dry_run_returns_plan_only(orchestrator: RunModeOrchestrator) -> None:
    harness = FakeHarness(FakePlan("test", 1.0, []))
    report = orchestrator.orchestrate("test_intent", RunMode.DRY_RUN, harness)
    assert report is not None


def test_resume_mode_loads_prior_state_and_executes_plan(
    orchestrator: RunModeOrchestrator,
) -> None:
    session_store = SessionStore()
    prior_state = {"plan": [FakeStep("step1", "hint", "art1")]}
    session_store.save("test_intent", prior_state)
    step = FakeStep("step1", "hint", "art1")
    plan = FakePlan("test", 1.0, [step])
    harness = FakeHarness(plan)
    _ = orchestrator.orchestrate("test_intent", RunMode.RESUME, harness)
    assert len(harness.executed_steps) == 1


def test_unsupported_mode_raises_value_error(orchestrator: RunModeOrchestrator) -> None:
    harness = FakeHarness(FakePlan("test", 1.0, []))
    with pytest.raises(ValueError, match="Unsupported run mode:"):
        orchestrator.orchestrate("test_intent", "unknown", harness)


def test_auto_mode_without_approval_queue_raises_value_error(
    orchestrator: RunModeOrchestrator,
) -> None:
    harness = FakeHarness(FakePlan("test", 1.0, []))
    with pytest.raises(ValueError, match="AUTO mode requires an approval queue"):
        orchestrator.orchestrate(
            "test_intent", RunMode.AUTO, harness, approval_queue=None
        )


def test_auto_mode_denied_approval_raises_permission_error(
    orchestrator: RunModeOrchestrator,
) -> None:
    step = FakeStep("high_step", "hint", "high_artifact")
    plan = FakePlan("test", 1.0, [step])
    harness = FakeHarness(plan)
    approval_queue = FakeApprovalQueueCLI({"high_step": False})
    with pytest.raises(PermissionError, match="Approval denied for high_step"):
        orchestrator.orchestrate("test_intent", RunMode.AUTO, harness, approval_queue)


def test_resume_mode_without_session_raises_file_not_found_error(
    orchestrator: RunModeOrchestrator,
) -> None:
    harness = FakeHarness(FakePlan("test", 1.0, []))
    with pytest.raises(FileNotFoundError, match="No prior session found"):
        orchestrator.orchestrate("missing_intent", RunMode.RESUME, harness)


def test_root_author_marker_present_in_source() -> None:
    path = Path("src/rootact/run_mode.py")
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in path.read_text()
    assert '__ract_name__ = "RACT"' in path.read_text()


def test_root_knot_sentinel_used_in_orchestrate_signature() -> None:
    import inspect

    instance = RunModeOrchestrator()
    sig = inspect.signature(instance.orchestrate)
    param = sig.parameters["approval_queue"]
    assert param.default is _RUN_MODE_ROOT_KNOT
