from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"


class _RootKnotType:
    """Sentinel for Root Knot default arguments."""


_ROOT_KNOT: _RootKnotType = _RootKnotType()

from typing import Any, Optional, Protocol

from rootact.session_store import SessionStore
from rootact.approval_queue_cli import ApprovalQueueCLI
from rootact.manager import Plan, Step
from rootact.executor import ExecutionReport
from rootact.rooted import Rooted


class HarnessLike(Protocol):
    """Protocol for the richer harness interface expected by RunModeOrchestrator."""

    def build_plan(self, intent: str) -> Plan: ...
    def run_plan(self, plan: Plan) -> Any: ...
    def run_step(self, step: Step) -> None: ...
    def finalize(self) -> Any: ...
    def plan_only(self, plan: Plan) -> Any: ...
    def build_plan_from_state(self, state: dict[str, Any], intent: str) -> Plan: ...


class RunMode:
    YOLO = "yolo"
    AUTO = "auto"
    DRY_RUN = "dry_run"
    RESUME = "resume"


class RunModeOrchestrator:
    def __init__(self) -> None:
        self.session_store = SessionStore()
        self.approval_queue = ApprovalQueueCLI()

    def orchestrate(
        self,
        intent: str,
        mode: str,
        harness: HarnessLike,
        approval_queue: Optional[ApprovalQueueCLI] | _RootKnotType = _ROOT_KNOT,
    ) -> "Rooted[ExecutionReport]":
        if isinstance(approval_queue, _RootKnotType):
            resolved_queue: Optional[ApprovalQueueCLI] = self.approval_queue
        else:
            resolved_queue = approval_queue

        if mode == RunMode.YOLO:
            report = self._execute_yolo(intent, harness)
        elif mode == RunMode.AUTO:
            if resolved_queue is None:
                raise ValueError("AUTO mode requires an approval queue")
            report = self._execute_auto(intent, harness, resolved_queue)
        elif mode == RunMode.DRY_RUN:
            report = self._dry_run(intent, harness)
        elif mode == RunMode.RESUME:
            report = self._resume_session(intent, harness)
        else:
            raise ValueError(f"Unsupported run mode: {mode}")
        return report

    def _execute_yolo(
        self, intent: str, harness: HarnessLike
    ) -> "Rooted[ExecutionReport]":
        plan = harness.build_plan(intent)
        execution_report = harness.run_plan(plan)
        return execution_report

    def _execute_auto(
        self, intent: str, harness: HarnessLike, approval_queue: ApprovalQueueCLI
    ) -> "Rooted[ExecutionReport]":
        plan = harness.build_plan(intent)
        for step in plan.steps:
            if step.expected_artifact.startswith("high_"):
                approval = approval_queue.prompt(step.action)
                if not approval:
                    raise PermissionError(f"Approval denied for {step.action}")
            harness.run_step(step)
        execution_report = harness.finalize()
        return execution_report

    def _dry_run(self, intent: str, harness: HarnessLike) -> "Rooted[ExecutionReport]":
        plan = harness.build_plan(intent)
        report = harness.plan_only(plan)
        return report

    def _resume_session(
        self, intent: str, harness: HarnessLike
    ) -> "Rooted[ExecutionReport]":
        try:
            prior_state = self.session_store.load(intent)
        except (FileNotFoundError, KeyError):
            raise FileNotFoundError(f"No prior session found for {intent}") from None
        if prior_state is None:
            raise FileNotFoundError(f"No prior session found for {intent}")
        plan = harness.build_plan_from_state(prior_state, intent)
        execution_report = harness.run_plan(plan)
        return execution_report
